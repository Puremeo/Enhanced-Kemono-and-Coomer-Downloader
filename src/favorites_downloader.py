import logging
from typing import List, Optional
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time as _time

from .config import load_config, get_domains
from .session import create_session
from .post_extractor import process_posts, extract_posts
from .batch_file_downloader import process_post, batch_download_posts

logger = logging.getLogger(__name__)


def _get_auth_headers(config):
    headers = {}
    if getattr(config, "coomer_api_token", None):
        headers["Authorization"] = f"Bearer {config.coomer_api_token}"
    return headers


def fetch_favorites_list(config) -> List[dict]:
    """Fetch the list of favorite accounts using Coomer API.

    Returns a list of account dicts (as returned by the API). This function
    expects either an API token in config.coomer_api_token or an authenticated
    session via cookies in config.coomer_cookie.
    """
    cfg = config
    domains = get_domains()
    base = domains.get("coomer")
    if not base:
        raise RuntimeError("Coomer domain not configured in domain.json")

    # Ensure base has a URL scheme (requests requires it). Default to https://
    if not base.startswith("http://") and not base.startswith("https://"):
        base = "https://" + base

    # Allow override of endpoint from config
    endpoint_override = getattr(cfg, "favorites_endpoint", None)
    # Use the endpoint observed in browser: /api/v1/account/favorites
    base_endpoint = endpoint_override or f"{base.rstrip('/')}/api/v1/account/favorites"

    sess = create_session(domain=base, config=cfg)

    results: List[dict] = []
    page = 1
    per_page = getattr(cfg, "favorites_page_size", 50)
    limit = getattr(cfg, "favorites_limit", None)
    rate = getattr(cfg, "favorites_rate_limit_seconds", 0.5)

    logger.info("Fetching favorites using endpoint %s (limit=%s)", base_endpoint, limit)

    while True:
        # Try page-based query first
        params = {"page": page, "limit": per_page}
        data = None
        # Browser-like headers observed in capture
        req_headers = {
            'Accept': 'text/css',
            'Referer': base.rstrip('/') + '/artists',
            'Origin': base,
            'User-Agent': sess.headers.get('User-Agent', 'Mozilla/5.0'),
        }
        try:
            resp = sess.get(base_endpoint, params=params, timeout=30)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                # fallback: try to parse text as JSON
                import json as _json

                try:
                    data = _json.loads(resp.text)
                except Exception:
                    data = None
        except Exception as e:
            # If Forbidden, try the server-recommended Accept header workaround
            try:
                if hasattr(e, 'response') and e.response is not None and getattr(e.response, 'status_code', None) == 403:
                    resp = sess.get(base_endpoint, params=params, headers=req_headers, timeout=30)
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except Exception:
                        import json as _json

                        try:
                            data = _json.loads(resp.text)
                        except Exception:
                            data = None
                else:
                    # Fallback: try without params (some instances return full list)
                    resp = sess.get(base_endpoint, headers=req_headers, timeout=30)
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except Exception:
                        import json as _json

                        try:
                            data = _json.loads(resp.text)
                        except Exception:
                            data = None
            except Exception:
                # As a last resort, try cookie-only session if cookies exist
                try:
                    cookie_only_sess = create_session(domain=base, config=cfg)
                    # remove Authorization header if present
                    if 'Authorization' in cookie_only_sess.headers:
                        cookie_only_sess.headers.pop('Authorization')
                    resp = cookie_only_sess.get(base_endpoint, params=params, headers=req_headers, timeout=30)
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except Exception:
                        import json as _json

                        try:
                            data = _json.loads(resp.text)
                        except Exception:
                            data = None
                except Exception:
                    raise

        # Extract list from response
        page_items = []
        if isinstance(data, list):
            page_items = data
        elif isinstance(data, dict):
            for k in ("favorites", "data", "accounts", "items"):
                if isinstance(data.get(k), list):
                    page_items = data.get(k)
                    break
        else:
            raise ValueError("Unexpected favorites list format from API")

        if not page_items:
            break

        results.extend(page_items)

        if limit and len(results) >= limit:
            results = results[:limit]
            break

        # If fewer than per_page returned, likely last page
        if len(page_items) < per_page:
            break

        page += 1
        time_to_sleep = float(rate)
        if time_to_sleep > 0:
            import time as _time

            _time.sleep(time_to_sleep)

    return results


def _process_single_account(acct: dict, base: str, base_dir: Path, config) -> Optional[str]:
    """Process a single account: extract posts and return JSON path."""
    service = acct.get("service")
    public_id = acct.get("public_id")
    acct_id = acct.get("id")

    if public_id:
        user_ident = public_id
    elif acct_id:
        user_ident = acct_id
    else:
        logger.warning("Skipping favorite account with no public_id/id: %r", acct)
        return None

    # Build profile URL
    base_with_scheme = base
    if not base_with_scheme.startswith("http://") and not base_with_scheme.startswith("https://"):
        base_with_scheme = "https://" + base_with_scheme

    profile_url = f"{base_with_scheme.rstrip('/')}/{service}/user/{user_ident}"
    logger.info("Extracting posts for account %s (%s)", user_ident, service)

    # Ensure directory for this account
    acct_dir = base_dir / str(user_ident)
    acct_dir.mkdir(parents=True, exist_ok=True)

    # Use existing extractor to build JSON for this profile
    try:
        json_path = extract_posts(profile_url, "all")
        if not json_path:
            logger.warning("No posts found for %s (extractor returned no JSON)", user_ident)
            return None
        return json_path
    except Exception as e:
        logger.warning("No posts found for %s (extractor error: %s)", user_ident, e)
        return None


def download_favorites(download_dir: Optional[str] = None, use_parallel: bool = True):
    """Main entry: fetch favorites and download their posts.

    For each favorite account returned by the API, this will try to fetch
    the account's posts (via the existing extractor) and then call the batch
    downloader to fetch media.
    
    Optimized with concurrent processing for faster link extraction.
    If use_parallel is True, downloads start as soon as posts are extracted for each account.
    """
    config = load_config()
    base_dir = Path(download_dir or ".")
    domains = get_domains()
    base = domains.get("coomer")
    if not base:
        raise RuntimeError("Coomer domain not configured in domain.json")

    session = create_session(domain=base, config=config)

    try:
        favs = fetch_favorites_list(config)
    except Exception as e:
        logger.exception("Failed to fetch favorites list: %s", e)
        raise

    logger.info("Found %d favorite accounts", len(favs))

    if use_parallel:
        # Parallel mode: extract and download simultaneously for each account
        from .parallel_extract_download import extract_and_download_parallel
        
        max_extract_workers = getattr(config, "favorites_extract_workers", 3)
        accounts_processed = 0
        accounts_failed = 0
        
        print(f"\nProcessing {len(favs)} favorite accounts in parallel mode...")
        print("(Each account will extract and download simultaneously)\n")
        
        with ThreadPoolExecutor(max_workers=max_extract_workers) as executor:
            futures = {}
            for acct in favs:
                service = acct.get("service")
                public_id = acct.get("public_id")
                acct_id = acct.get("id")
                
                if public_id:
                    user_ident = public_id
                elif acct_id:
                    user_ident = acct_id
                else:
                    logger.warning("Skipping favorite account with no public_id/id: %r", acct)
                    continue
                
                # Build profile URL
                base_with_scheme = base
                if not base_with_scheme.startswith("http://") and not base_with_scheme.startswith("https://"):
                    base_with_scheme = "https://" + base_with_scheme
                
                profile_url = f"{base_with_scheme.rstrip('/')}/{service}/user/{user_ident}"
                
                # Ensure directory for this account
                acct_dir = base_dir / str(user_ident)
                acct_dir.mkdir(parents=True, exist_ok=True)
                
                # Submit parallel extract and download task
                future = executor.submit(extract_and_download_parallel, profile_url, "all")
                futures[future] = (user_ident, service)
            
            # Wait for all accounts to complete
            for future in as_completed(futures):
                user_ident, service = futures[future]
                try:
                    future.result()
                    accounts_processed += 1
                    print(f"✓ Completed account: {user_ident} ({service})")
                except Exception as e:
                    accounts_failed += 1
                    logger.exception("Error processing account %s: %s", user_ident, e)
                    print(f"❌ Failed account: {user_ident} ({service}) - {e}")
        
        print(f"\n✓ Favorites download completed!")
        print(f"  Processed: {accounts_processed}/{len(favs)} accounts")
        print(f"  Failed: {accounts_failed} accounts")
    else:
        # Traditional mode: extract all first, then download all
        max_extract_workers = getattr(config, "favorites_extract_workers", 3)
        max_download_workers = getattr(config, "favorites_download_workers", 2)
        
        # Phase 1: Concurrently extract posts for all accounts
        logger.info("Phase 1: Extracting posts for all accounts (using %d workers)...", max_extract_workers)
        json_paths = []
        
        with ThreadPoolExecutor(max_workers=max_extract_workers) as executor:
            futures = {}
            for acct in favs:
                future = executor.submit(_process_single_account, acct, base, base_dir, config)
                futures[future] = acct
            
            for future in as_completed(futures):
                acct = futures[future]
                try:
                    json_path = future.result()
                    if json_path:
                        json_paths.append(json_path)
                        user_ident = acct.get("public_id") or acct.get("id")
                        logger.info("✓ Extracted posts for %s", user_ident)
                except Exception as e:
                    user_ident = acct.get("public_id") or acct.get("id")
                    logger.exception("Error extracting posts for %s: %s", user_ident, e)
        
        logger.info("Phase 1 complete: Extracted posts for %d/%d accounts", len(json_paths), len(favs))
        
        # Phase 2: Concurrently download posts
        if json_paths:
            logger.info("Phase 2: Downloading posts (using %d workers)...", max_download_workers)
            with ThreadPoolExecutor(max_workers=max_download_workers) as executor:
                futures = {}
                for json_path in json_paths:
                    future = executor.submit(batch_download_posts, json_path)
                    futures[future] = json_path
                
                for future in as_completed(futures):
                    json_path = futures[future]
                    try:
                        future.result()
                        logger.info("✓ Downloaded posts from %s", json_path)
                    except Exception as e:
                        logger.exception("Error downloading posts from %s: %s", json_path, e)
            
            logger.info("Phase 2 complete: Downloaded posts for %d accounts", len(json_paths))
        else:
            logger.warning("No posts to download")
