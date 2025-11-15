from typing import Dict, Optional

import requests

from .config import get_domains, load_config, save_config, Config

init_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'DNT': '1',
    'Sec-GPC': '1',
    'Upgrade-Insecure-Requests': '1',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Priority': 'u=0, i',
}
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0',
    'Accept': 'text/css',
    'Accept-Language': 'en-US,en;q=0.5',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
}

# Map of service -> Cookies
cookie_map: Dict[str, Dict[str, str]] = dict()


def _parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    """Parse a cookie string like 'a=1; b=2' into a dict."""
    result: Dict[str, str] = {}
    for part in cookie_str.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            result[k] = v
    return result


def create_session(domain: Optional[str] = None, config: Optional[Config] = None) -> requests.Session:
    """Create a requests.Session preconfigured with headers and optional auth.

    Behavior:
    - If `config` provided (or loaded), and contains `coomer_api_token`, sets
      Authorization: Bearer <token> header.
    - If `config` contains `coomer_cookie` (string), those cookies are loaded
      into the session.
    - If `domain` is omitted, uses configured Coomer domain from domain.json.
    """
    if config is None:
        config = load_config()

    sess = requests.Session()
    sess.headers.update(init_headers)

    # Apply API token auth if present
    token = getattr(config, "coomer_api_token", None)
    if token:
        sess.headers["Authorization"] = f"Bearer {token}"

    # Apply cookie string if present
    cookie_str = getattr(config, "coomer_cookie", None)
    if cookie_str:
        sess.cookies.update(_parse_cookie_string(cookie_str))

    # If domain provided as hostname only, prefix with scheme
    if domain is None:
        domains = get_domains()
        domain = domains.get("coomer")

    # Ensure cookie_map is seeded for convenience
    try:
        cookie_map_key = domain
        cookie_map[cookie_map_key] = sess.cookies.get_dict()
    except Exception:
        pass

    return sess


def save_api_token(token: str, config_path: str = "config/conf.json") -> None:
    cfg = load_config(config_path)
    cfg.coomer_api_token = token
    save_config(cfg, config_path)


def save_cookie_string(cookie_str: str, config_path: str = "config/conf.json") -> None:
    cfg = load_config(config_path)
    cfg.coomer_cookie = cookie_str
    save_config(cfg, config_path)


def login_with_saved_credentials(domain: Optional[str] = None, save_cookie: bool = True) -> Optional[requests.Session]:
    """Attempt to login using saved username/password from config.

    Returns the logged-in requests.Session on success, or None on failure.
    This method does not print or log the password.
    
    First tries API login, then falls back to form-based login.
    """
    cfg = load_config()
    username = getattr(cfg, "coomer_username", None)
    password = getattr(cfg, "coomer_password", None)

    if not username or not password:
        return None

    # Try API login first (preferred method)
    try:
        sess = login_with_api(username, password, domain=domain, save_cookie=save_cookie)
        return sess
    except Exception:
        # Fall back to form-based login
        pass

    # Try common form payload shapes
    payloads = [
        {"email": username, "password": password},
        {"user[email]": username, "user[password]": password},
        {"username": username, "password": password},
    ]

    last_exc = None
    for payload in payloads:
        try:
            sess = login_with_form("/users/sign_in", payload, domain=domain, save_cookie=save_cookie)
            return sess
        except Exception as e:
            last_exc = e
            continue

    # If we reach here, no method succeeded
    if last_exc:
        raise last_exc
    return None


def save_credentials(username: str, password: str, config_path: str = "config/conf.json") -> None:
    cfg = load_config(config_path)
    cfg.coomer_username = username
    cfg.coomer_password = password
    save_config(cfg, config_path)


def clear_saved_credentials(config_path: str = "config/conf.json") -> None:
    cfg = load_config(config_path)
    cfg.coomer_username = None
    cfg.coomer_password = None
    save_config(cfg, config_path)


def login_with_api(username: str, password: str, domain: Optional[str] = None, save_cookie: bool = True) -> requests.Session:
    """Login using the Coomer API endpoint.
    
    This is the preferred method as it uses the official API endpoint:
    POST /api/v1/authentication/login
    
    Args:
        username: Username or email
        password: Password
        domain: Optional domain override
        save_cookie: Whether to save cookies to config
        
    Returns:
        Authenticated requests.Session with cookies set
        
    Raises:
        requests.HTTPError: If login fails
    """
    domains = get_domains()
    base = domain or domains.get("coomer")
    if base is None:
        raise RuntimeError("Coomer domain not configured")
    
    # Normalize base URL
    if not base.startswith("http://") and not base.startswith("https://"):
        base = "https://" + base
    
    # Use the API endpoint
    login_url = base.rstrip("/") + "/api/v1/authentication/login"
    login_page_url = base.rstrip("/") + "/authentication/login"
    
    # Create a fresh session (don't load saved cookies to avoid conflicts)
    sess = requests.Session()
    
    # Set headers to match browser request exactly
    browser_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0',
        'Accept': 'text/css',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Content-Type': 'application/json',
        'Origin': base,
        'Referer': login_page_url,
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'Priority': 'u=1, i',
    }
    sess.headers.update(browser_headers)
    
    # Step 1: Visit login page first to get initial cookies (like browser does)
    # This is important to get DDoS protection cookies and initial session
    try:
        sess.get(login_page_url, timeout=30)
    except Exception:
        # If this fails, continue anyway - might still work
        pass
    
    # Step 2: Clear any existing session cookie to avoid conflicts
    if 'session' in sess.cookies:
        del sess.cookies['session']
    
    # Try different payload formats - API might expect "username" or "email"
    # Try "username" first (based on error message "Username is required.")
    payloads_to_try = [
        {"username": username, "password": password},  # Try username first
        {"email": username, "password": password},    # Fallback to email
        {"username": username, "email": username, "password": password},  # Both fields
    ]
    
    resp = None
    last_error = None
    
    # Step 3: Try different payload formats
    for json_payload in payloads_to_try:
        try:
            resp = sess.post(login_url, json=json_payload, timeout=30)
            
            # Handle 409 CONFLICT - might mean we need to clear session and retry
            if resp.status_code == 409:
                # Clear session cookie and retry once
                if 'session' in sess.cookies:
                    del sess.cookies['session']
                # Also clear from cookie jar
                for cookie in list(sess.cookies):
                    if cookie.name == 'session':
                        sess.cookies.clear(cookie.domain, cookie.path, cookie.name)
                
                # Retry the login with same payload
                resp = sess.post(login_url, json=json_payload, timeout=30)
            
            # If successful (200), break out of loop
            if resp.status_code == 200:
                break
                
            # If we get a clear error message, check if it's about field name
            if resp.status_code != 200:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get('error', error_data.get('message', ''))
                    # If error says username/email is required, try next payload format
                    if 'required' in error_msg.lower() or 'invalid' in error_msg.lower():
                        last_error = error_msg
                        continue  # Try next payload format
                    else:
                        # Other error, raise it
                        raise requests.HTTPError(f"Login failed: {error_msg}")
                except (ValueError, KeyError, AttributeError):
                    # Can't parse error, try next payload
                    continue
                    
        except requests.HTTPError as e:
            # If it's not about field format, re-raise
            if resp and resp.status_code not in (400, 422):
                raise
            last_error = str(e)
            continue
        except Exception as e:
            last_error = str(e)
            continue
    
    # If we tried all payloads and still failed
    if not resp or resp.status_code != 200:
        if last_error:
            raise requests.HTTPError(f"Login failed: {last_error}")
        elif resp:
            # Try to get error message from response
            try:
                error_data = resp.json()
                error_msg = error_data.get('error', error_data.get('message', f'HTTP {resp.status_code}'))
                raise requests.HTTPError(f"Login failed: {error_msg}")
            except (ValueError, KeyError, AttributeError):
                resp.raise_for_status()
        else:
            raise requests.HTTPError("Login failed: All payload formats failed")
    
    # Check if we got a session cookie (indicates successful login)
    session_cookie = sess.cookies.get('session')
    if not session_cookie:
        # Try to parse response to see if there's an error message
        try:
            error_data = resp.json()
            error_msg = error_data.get('error', error_data.get('message', 'Login failed: No session cookie received'))
            raise requests.HTTPError(f"Login failed: {error_msg}")
        except (ValueError, KeyError):
            raise requests.HTTPError("Login failed: No session cookie received. Check username and password.")
    
    # Save cookies if requested
    if save_cookie:
        cookie_items = [f"{k}={v}" for k, v in sess.cookies.get_dict().items()]
        cookie_str = "; ".join(cookie_items)
        save_cookie_string(cookie_str)
    
    return sess


def login_with_form(login_path: str, payload: Dict[str, str], domain: Optional[str] = None, save_cookie: bool = True) -> requests.Session:
    """Generic form-based login helper.

    This helper intentionally does not assume the exact login fields used by a
    particular Coomer instance. Caller should provide `login_path` (e.g.
    '/auth/sign_in' or '/users/sign_in') and the expected form `payload`.

    On success (HTTP 200/302), the session cookies will be optionally saved to
    config.coomer_cookie if `save_cookie` is True.
    """
    domains = get_domains()
    base = domain or domains.get("coomer")
    if base is None:
        raise RuntimeError("Coomer domain not configured")

    # Normalize base and construct absolute URL for login page
    if not base.startswith("http://") and not base.startswith("https://"):
        base = "https://" + base

    login_url = base.rstrip("/") + login_path
    sess = create_session(domain=base)

    # Step 1: GET the login page to collect cookies and hidden fields (CSRF tokens)
    resp = sess.get(login_url, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # Attempt to find form action and hidden inputs (naive but practical)
    import re
    form_action = None
    m = re.search(r"<form[^>]+action=[\"']?([^\"' >]+)", html, re.IGNORECASE)
    if m:
        form_action = m.group(1)

    # If action is relative, make absolute
    if form_action and not form_action.startswith("http"):
        if form_action.startswith("/"):
            action_url = base.rstrip("/") + form_action
        else:
            action_url = base.rstrip("/") + "/" + form_action
    else:
        action_url = form_action or login_url

    # Extract hidden inputs
    hidden_fields = dict()
    for hid in re.finditer(r"<input[^>]+type=[\"']hidden[\"'][^>]*>", html, re.IGNORECASE):
        inp = hid.group(0)
        name_m = re.search(r"name=[\"']?([^\"' >]+)", inp, re.IGNORECASE)
        value_m = re.search(r"value=[\"']?([^\"' >]+)", inp, re.IGNORECASE)
        if name_m:
            name = name_m.group(1)
            value = value_m.group(1) if value_m else ""
            hidden_fields[name] = value

    # Merge payload with hidden fields (payload overrides hidden fields)
    form_data = {**hidden_fields, **payload}

    # Some servers expect a referer and common browser headers
    headers = sess.headers.copy()
    headers.setdefault("Referer", login_url)
    headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")

    # Step 2: POST to the action URL
    post_url = action_url
    post_resp = sess.post(post_url, data=form_data, headers=headers, allow_redirects=True, timeout=30)
    # Accept both 200/302; raise for other errors
    if post_resp.status_code >= 400:
        post_resp.raise_for_status()

    if save_cookie:
        cookie_items = [f"{k}={v}" for k, v in sess.cookies.get_dict().items()]
        cookie_str = "; ".join(cookie_items)
        save_cookie_string(cookie_str)

    return sess
