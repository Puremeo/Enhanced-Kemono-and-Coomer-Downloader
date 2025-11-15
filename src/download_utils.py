import os
import time
import requests
from typing import Optional, Tuple, Dict, Any
from tqdm import tqdm


def _get_total_size(url: str, headers: Optional[Dict[str, str]] = None, cookies: Optional[Dict[str, str]] = None) -> Optional[int]:
    try:
        r = requests.head(url, headers=headers or {}, cookies=cookies, allow_redirects=True, timeout=10)
        if r.status_code >= 400:
            return None
        cl = r.headers.get("content-length")
        if cl is None:
            return None
        return int(cl)
    except Exception:
        return None


def download_with_resume(
    url: str,
    file_path: str,
    headers: Optional[Dict[str, str]] = None,
    cookies: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    chunk_size: int = 8192,
    show_progress: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Download a file with resume support.

    - Uses a temporary file at file_path + '.part' while downloading.
    - If a partial exists, attempts to resume using Range header.
    - On success, atomically replaces final file.
    - Returns (True, None) on success, (False, error_message) on failure.
    """
    temp_path = file_path + ".part"

    # Ensure parent dir exists
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or '.', exist_ok=True)

    attempt = 0
    while attempt < max_retries:
        try:
            # If final exists and seems complete, return success
            total_size = _get_total_size(url, headers=headers, cookies=cookies)
            if os.path.exists(file_path) and total_size is not None:
                if os.path.getsize(file_path) == total_size:
                    return True, None
                else:
                    # Move the incomplete final file to .part for resuming
                    try:
                        os.replace(file_path, temp_path)
                    except Exception:
                        # if move fails, try to remove final and proceed
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass

            existing_size = 0
            if os.path.exists(temp_path):
                existing_size = os.path.getsize(temp_path)

            # If server doesn't provide total_size and we have a non-zero existing_size,
            # we will attempt to resume, but if server doesn't support Range, we'll restart.

            req_headers = dict(headers or {})
            if existing_size > 0:
                req_headers["Range"] = f"bytes={existing_size}-"

            with requests.get(url, headers=req_headers, cookies=cookies, stream=True, timeout=30) as r:
                # Handle 416 or other unexpected statuses by restarting
                if r.status_code in (416,):
                    # clear temp and retry from scratch
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    attempt += 1
                    time.sleep(backoff_factor * (2 ** attempt))
                    continue

                # If server ignored Range and returned 200 but we had existing_size>0, restart
                if existing_size > 0 and r.status_code == 200:
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    existing_size = 0

                # Accept 200 or 206
                if r.status_code >= 400:
                    raise requests.HTTPError(f"HTTP {r.status_code}")

                mode = "ab" if existing_size > 0 else "wb"
                written = existing_size

                # If content-length provided for this response, compute expected
                resp_cl = r.headers.get("content-length")
                total_size = None
                if resp_cl:
                    resp_size = int(resp_cl)
                    if existing_size > 0:
                        # For resume, total_size is existing + remaining bytes
                        total_size = existing_size + resp_size
                    else:
                        total_size = resp_size
                else:
                    # Try to get total size from initial check
                    total_size = _get_total_size(url, headers=headers, cookies=cookies)
                    if total_size is None:
                        total_size = 0  # Unknown size

                # Get filename for progress bar
                filename = os.path.basename(file_path)
                
                # Open temp file and write with progress bar
                with open(temp_path, mode) as fh:
                    if show_progress and total_size > 0:
                        # Create progress bar
                        pbar = tqdm(
                            total=total_size,
                            initial=existing_size,
                            unit='B',
                            unit_scale=True,
                            unit_divisor=1024,
                            desc=filename[:50],  # Limit filename length
                            leave=False,
                            ncols=100,
                            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
                        )
                    else:
                        pbar = None
                    
                    try:
                        for chunk in r.iter_content(chunk_size=chunk_size):
                            if not chunk:
                                continue
                            fh.write(chunk)
                            written += len(chunk)
                            if pbar:
                                pbar.update(len(chunk))
                    finally:
                        if pbar:
                            pbar.close()

            # At this point download completed
            try:
                os.replace(temp_path, file_path)
            except Exception:
                # fallback: try copy then remove
                try:
                    with open(temp_path, "rb") as fr, open(file_path, "wb") as fw:
                        while True:
                            buf = fr.read(8192)
                            if not buf:
                                break
                            fw.write(buf)
                    os.remove(temp_path)
                except Exception as ex:
                    return False, f"Failed to finalize download: {ex}"

            return True, None

        except Exception as e:
            attempt += 1
            # If we've exhausted retries, return failure but leave .part for manual resume
            if attempt >= max_retries:
                return False, str(e)
            time.sleep(backoff_factor * (2 ** (attempt - 1)))

    return False, "Unknown error"
