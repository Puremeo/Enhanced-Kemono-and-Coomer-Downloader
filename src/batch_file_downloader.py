import os
import json
import re
import time
import requests
import signal
from typing import Dict, List, Tuple, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from tqdm import tqdm

from src.session import headers, cookie_map
from .download_utils import download_with_resume
from .config import load_config, Config
from .format_helpers import sanitize_filename, sanitize_title
from .failure_handlers import add_failed_download, remove_failed_download


def download_file(file_url: str, save_path: str) -> Tuple[bool, Optional[str]]:
    """
    Download a file from a URL and save it to the specified path.
    Returns (success, error_message) tuple.
    Progress bar is handled by download_with_resume.
    """
    try:
        try:
            cfg = load_config()
            domain = "kemono" if "kemono" in file_url else "coomer"
            success, error = download_with_resume(
                file_url,
                save_path,
                headers=headers,
                cookies=cookie_map.get(domain),
                max_retries=cfg.download_retries if hasattr(cfg, 'download_retries') else 3,
                backoff_factor=cfg.download_backoff if hasattr(cfg, 'download_backoff') else 1.0,
                chunk_size=8192,
                show_progress=True,
            )
            if success:
                remove_failed_download(file_url)
                return True, None
            else:
                add_failed_download(file_url)
                return False, error
        except Exception as e:
            add_failed_download(file_url)
            return False, str(e)

    except requests.exceptions.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        print(f"❌ Download failed {file_url}: {error_msg}")
        add_failed_download(file_url)
        return False, error_msg
    except IOError as e:
        error_msg = f"File I/O error: {str(e)}"
        print(f"❌ Failed to save file {save_path}: {error_msg}")
        add_failed_download(file_url)
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(f"❌ Download failed {file_url}: {error_msg}")
        add_failed_download(file_url)
        return False, error_msg


def process_post(
    post: Dict[str, Any], base_folder: str, config: Config
) -> Dict[str, Any]:
    """
    Process a single post, downloading its files.
    Returns statistics about the download.
    """
    post_id = post.get("id")

    # Determine folder name based on config
    if config.post_folder_name == "title":
        post_title = post.get("title", "").strip()
        if post_title:
            # Sanitize title for folder name
            sanitized_title = sanitize_title(post_title)
            folder_name = f"{post_id}_{sanitized_title}"
        else:
            folder_name = post_id
    else:
        folder_name = post_id

    post_folder = os.path.join(base_folder, folder_name)
    os.makedirs(post_folder, exist_ok=True)

    print(f"\nProcessing post ID {post_id}")
    if config.post_folder_name == "title" and post.get("title"):
        print(f"Title: {post.get('title')}")

    # Prepare downloads for this post
    downloads: List[Tuple[str, str]] = []
    for file_index, file in enumerate(post.get("files", []), start=1):
        original_name = file.get("name")
        file_url = file.get("url")
        sanitized_name = sanitize_filename(original_name)
        new_filename = f"{file_index}-{sanitized_name}"
        file_save_path = os.path.join(post_folder, new_filename)
        downloads.append((file_url, file_save_path))

    # Track download results
    total_files = len(downloads)
    successful = 0
    failed = []

    # Get concurrent download workers from config
    max_workers = getattr(config, "download_max_workers", 5)
    verify_workers = getattr(config, "file_verify_workers", 10)  # More workers for verification
    
    # Phase 1: Fast pre-check - batch check all files locally first
    files_to_verify = []  # Files that need remote verification
    files_to_download = []  # Files that need downloading
    skipped_count = 0
    
    if config.skip_existed_files:
        print(f"Pre-checking {total_files} files...")
        for file_url, file_save_path in downloads:
            part_path = file_save_path + ".part"
            final_exists = os.path.exists(file_save_path)
            part_exists = os.path.exists(part_path)
            
            # If .part file exists, always download (don't skip) - it's an incomplete download
            if part_exists:
                files_to_download.append((file_url, file_save_path))
                continue
            
            if final_exists:
                # Quick check: if file exists and has reasonable size (>0), assume it's complete
                # Only verify remotely if file size is 0 or verification is explicitly enabled
                try:
                    existing_size = os.path.getsize(file_save_path)
                    # Fast path: if file has content (>0 bytes), skip remote verification
                    # This significantly speeds up when most files are already downloaded
                    if existing_size > 0:
                        # Optionally verify: only if config requires strict verification
                        strict_verify = getattr(config, "strict_file_verification", False)
                        if strict_verify:
                            files_to_verify.append((file_url, file_save_path, existing_size))
                        else:
                            # Fast skip: assume complete if file exists and has content
                            skipped_count += 1
                            continue
                    else:
                        # File exists but is empty, need to verify or re-download
                        files_to_verify.append((file_url, file_save_path, existing_size))
                except OSError:
                    # Can't read file, need to download
                    files_to_download.append((file_url, file_save_path))
            else:
                # File doesn't exist, need to download
                files_to_download.append((file_url, file_save_path))
    else:
        # Skip checking if disabled
        files_to_download = downloads.copy()
    
    if skipped_count > 0:
        print(f"✓ Fast-skipped {skipped_count} existing files (assumed complete)")
    
    # Phase 2: Concurrently verify files that need remote size check
    if files_to_verify:
        print(f"Verifying {len(files_to_verify)} files with remote server...")
        
        def verify_file(file_url: str, file_save_path: str, existing_size: int) -> Tuple[bool, str]:
            """Verify if local file matches remote size. Returns (is_complete, file_path)"""
            try:
                response = requests.head(file_url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    expected_size = int(response.headers.get("content-length", 0))
                    if expected_size > 0 and existing_size == expected_size:
                        return True, file_save_path
                    elif expected_size > 0:
                        # Size mismatch, need to re-download
                        try:
                            part_path = file_save_path + ".part"
                            os.replace(file_save_path, part_path)
                        except Exception:
                            try:
                                os.remove(file_save_path)
                            except Exception:
                                pass
                        return False, file_save_path
                return False, file_save_path
            except Exception:
                # On error, assume need to download
                return False, file_save_path
        
        with ThreadPoolExecutor(max_workers=verify_workers) as verify_executor:
            verify_futures = {
                verify_executor.submit(verify_file, url, path, size): (url, path)
                for url, path, size in files_to_verify
            }
            
            for future in as_completed(verify_futures):
                url, path = verify_futures[future]
                try:
                    is_complete, file_path = future.result()
                    if is_complete:
                        skipped_count += 1
                        filename = os.path.basename(file_path)
                        print(f"Skipped (verified): {filename}")
                    else:
                        files_to_download.append((url, file_path))
                except Exception:
                    # On error, add to download list
                    files_to_download.append((url, path))
    
    # Phase 3: Download remaining files
    files_to_download_count = len(files_to_download)
    if files_to_download_count > 0:
        print(f"\nDownloading {files_to_download_count} files...")
        
        # Create overall progress bar for all files
        overall_pbar = tqdm(
            total=files_to_download_count,
            desc=f"Post {post_id}",
            unit="file",
            position=0,
            leave=True,
            ncols=100,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} files [{elapsed}<{remaining}]'
        )
    else:
        print(f"All {total_files} files are already downloaded!")
        return {
            "post_id": post_id,
            "total_files": total_files,
            "successful": total_files,
            "failed": [],
        }

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all downloads and collect futures
            futures = []
            for file_url, file_save_path in files_to_download:
                future = executor.submit(download_file, file_url, file_save_path)
                futures.append((future, file_url, file_save_path))

            # Wait for all downloads to complete
            for future, file_url, file_save_path in futures:
                try:
                    success, error_msg = future.result()
                    if success:
                        successful += 1
                        overall_pbar.update(1)
                    else:
                        failed.append(
                            {
                                "url": file_url,
                                "path": file_save_path,
                                "error": error_msg,
                            }
                        )
                        overall_pbar.update(1)
                except KeyboardInterrupt:
                    print("\n⚠️ Download interrupted by user (Ctrl+C)")
                    print("Cancelling remaining downloads...")
                    # Cancel remaining futures
                    for remaining_future, _, _ in futures:
                        remaining_future.cancel()
                    break
    except KeyboardInterrupt:
        print("\n⚠️ Download interrupted by user (Ctrl+C)")
        print("Cancelling all downloads...")
        # The executor context manager will handle cleanup
    finally:
        if files_to_download_count > 0:
            overall_pbar.close()

    # Add skipped files to successful count
    successful += skipped_count

    # Print summary
    if failed:
        print(
            f"⚠️ Post {post_id} completed with errors: {successful}/{total_files} files (skipped {skipped_count}, downloaded {successful - skipped_count}, failed {len(failed)})"
        )
        for fail in failed:
            print(f"   ❌ Failed: {os.path.basename(fail['path'])}")
    else:
        print(f"✅ Post {post_id} completed: all {successful} files (skipped {skipped_count}, downloaded {successful - skipped_count})")

    return {
        "post_id": post_id,
        "total_files": total_files,
        "successful": successful,
        "failed": failed,
    }


def batch_download_posts(json_file_path: str, post_id: str = None) -> None:
    """
    Download posts from JSON file in batch mode.

    :param json_file_path: Path to the JSON file containing post data
    :param post_id: Optional specific post ID to download, if None downloads all posts
    """
    # Check if the file exists
    if not os.path.exists(json_file_path):
        raise FileNotFoundError(f"The file '{json_file_path}' was not found.")

    # Load the JSON file
    with open(json_file_path, "r", encoding="utf-8") as f:
        profile_metadata = json.load(f)

    # Base folder for posts
    base_folder = os.path.join(os.path.dirname(json_file_path), "posts")
    os.makedirs(base_folder, exist_ok=True)

    # Load configuration from JSON file
    config = load_config()

    posts = profile_metadata.get("posts", [])

    # Filter for specific post if post_id is provided
    if post_id:
        posts = [post for post in posts if post.get("id") == post_id]
        if not posts:
            print(f"Post ID {post_id} not found in JSON file")
            return
    else:
        # Sort posts by their ID field (default: oldest first)
        posts = sorted(posts, key=lambda post: post.get("id", ""))
        # Reverse to descending order (newest first)
        if not config.process_from_oldest:
            posts = list(reversed(posts))

    # Process each post sequentially (with reduced delay)
    post_delay = getattr(config, "post_download_delay_seconds", 0.5)  # Default 0.5s instead of 2s
    for post_index, post in enumerate(posts, start=1):
        process_post(post, base_folder, config)
        if post_delay > 0:
            time.sleep(post_delay)


def main() -> None:
    """Command line interface for backward compatibility"""
    if len(sys.argv) < 2:
        print("Usage: python batch_file_downloader.py {json_path} [post_id]")
        sys.exit(1)

    json_file_path = sys.argv[1]
    post_id = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        batch_download_posts(json_file_path, post_id)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
