"""
Parallel extraction and download module.
Allows downloading posts while they are still being extracted.
"""
import os
import json
from queue import Queue, Empty
from threading import Event, Thread
from typing import Dict, List, Any, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import load_config, Config
from .post_extractor import extract_posts_streaming, get_base_config, get_artist_dir
from .batch_file_downloader import process_post
from .format_helpers import sanitize_title


def extract_and_download_parallel(profile_url: str, fetch_mode: str = "all") -> None:
    """
    Extract posts and download them in parallel.
    Posts are downloaded as soon as they are extracted, without waiting for all extraction to complete.
    
    Args:
        profile_url: URL of the profile to extract posts from
        fetch_mode: Mode for fetching posts ("all", page number, or range)
    """
    config = load_config()
    
    # Get base configuration
    BASE_API_URL, BASE_SERVER, BASE_DIR = get_base_config(profile_url)
    domain = profile_url.split("/")[2]
    
    # Get artist info for folder structure
    from .post_extractor import get_artist_info, fetch_user
    service, user_id = get_artist_info(profile_url)
    user_data = fetch_user(BASE_API_URL, service, domain, user_id)
    name = user_data["name"]
    
    # Setup directories
    base_dir = BASE_DIR
    artist_dir_name = get_artist_dir(name, service, user_id)
    artist_dir = os.path.join(base_dir, artist_dir_name)
    posts_folder = os.path.join(artist_dir, "posts")
    os.makedirs(posts_folder, exist_ok=True)
    
    # Queue for posts ready to download
    post_queue = Queue(maxsize=10)  # Limit queue size to prevent memory issues
    extraction_done = Event()
    # Use thread-safe dictionary for stats
    from threading import Lock
    stats_lock = Lock()
    download_stats = {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    
    def extraction_worker():
        """Worker thread that extracts posts and puts them in the queue"""
        try:
            for post in extract_posts_streaming(profile_url, fetch_mode):
                with stats_lock:
                    download_stats["total"] += 1
                try:
                    post_queue.put(post, timeout=10)  # Add timeout to prevent blocking forever
                except Exception as e:
                    print(f"Warning: Could not put post in queue: {e}")
                    # Continue with next post even if queue is full
        except Exception as e:
            print(f"Error during extraction: {e}")
            import traceback
            traceback.print_exc()
        finally:
            extraction_done.set()
            # Don't put sentinel here - let main thread handle it after join()
    
    def download_worker():
        """Worker thread that downloads posts from the queue"""
        while True:
            post = None
            try:
                # Get post from queue with timeout
                try:
                    post = post_queue.get(timeout=1)
                except Empty:
                    if extraction_done.is_set():
                        break
                    continue
                
                # Check for sentinel
                if post is None:
                    # Don't call task_done() for sentinel
                    break
                
                # Process the post
                try:
                    # Determine folder name
                    post_id = post.get("id")
                    if config.post_folder_name == "title":
                        post_title = post.get("title", "").strip()
                        if post_title:
                            sanitized_title = sanitize_title(post_title)
                            folder_name = f"{post_id}_{sanitized_title}"
                        else:
                            folder_name = post_id
                    else:
                        folder_name = post_id
                    
                    post_folder = os.path.join(posts_folder, folder_name)
                    os.makedirs(post_folder, exist_ok=True)
                    
                    # Check if already downloaded
                    expected_files = len(post.get("files", []))
                    if expected_files > 0:
                        existing_files = [
                            f for f in os.listdir(post_folder)
                            if os.path.isfile(os.path.join(post_folder, f))
                        ]
                        if len(existing_files) == expected_files:
                            with stats_lock:
                                download_stats["skipped"] += 1
                            # task_done() will be called in finally block
                            continue
                    
                    # Download the post
                    result = process_post(post, posts_folder, config)
                    with stats_lock:
                        if result["successful"] == result["total_files"]:
                            download_stats["downloaded"] += 1
                        else:
                            download_stats["failed"] += 1
                        
                except Exception as e:
                    print(f"Error downloading post {post.get('id', 'unknown')}: {e}")
                    import traceback
                    traceback.print_exc()
                    with stats_lock:
                        download_stats["failed"] += 1
                finally:
                    # Only call task_done() if we got a real post (not sentinel)
                    if post is not None:
                        post_queue.task_done()
                    
            except Exception as e:
                print(f"Error in download worker: {e}")
                import traceback
                traceback.print_exc()
                # If we got a post before the exception, mark it as done
                if post is not None:
                    try:
                        post_queue.task_done()
                    except ValueError:
                        pass  # Already called
                break
    
    # Start extraction thread
    extract_thread = Thread(target=extraction_worker, daemon=True)
    extract_thread.start()
    
    # Start download workers
    download_workers_count = getattr(config, "parallel_download_workers", 3)
    download_threads = []
    for _ in range(download_workers_count):
        thread = Thread(target=download_worker, daemon=True)
        thread.start()
        download_threads.append(thread)
    
    # Create progress bar with dynamic total (will be updated as we go)
    print(f"\nExtracting and downloading posts in parallel...")
    
    # Monitor progress with simple print updates instead of tqdm to avoid initialization issues
    import time
    last_total = 0
    last_downloaded = 0
    last_skipped = 0
    last_failed = 0
    
    # Wait for extraction to complete while monitoring progress
    while not extraction_done.is_set() or not post_queue.empty():
        with stats_lock:
            current_total = download_stats["total"]
            current_downloaded = download_stats["downloaded"]
            current_skipped = download_stats["skipped"]
            current_failed = download_stats["failed"]
        
        # Print progress update if changed
        if (current_total != last_total or current_downloaded != last_downloaded or 
            current_skipped != last_skipped or current_failed != last_failed):
            print(f"\rProgress: Extracted: {current_total}, Downloaded: {current_downloaded}, "
                  f"Skipped: {current_skipped}, Failed: {current_failed}", end="", flush=True)
            last_total = current_total
            last_downloaded = current_downloaded
            last_skipped = current_skipped
            last_failed = current_failed
        
        time.sleep(0.5)
    
    # Wait for extraction to complete
    extract_thread.join()
    
    # Wait for all posts to be processed (all task_done() calls completed)
    try:
        post_queue.join()
    except Exception:
        pass  # Ignore errors during join
    
    # Signal download workers to stop by putting sentinels
    # Note: sentinels don't need task_done() - they're handled specially in worker
    for _ in range(download_workers_count):
        try:
            post_queue.put(None, timeout=5)
        except Exception:
            pass  # Queue might be full, continue anyway
    
    # Wait for download workers to finish
    for thread in download_threads:
        thread.join(timeout=30)  # Add timeout to prevent hanging
    
    # Final update
    with stats_lock:
        final_total = download_stats["total"]
        final_downloaded = download_stats["downloaded"]
        final_skipped = download_stats["skipped"]
        final_failed = download_stats["failed"]
    
    # Print final status
    print(f"\rProgress: Extracted: {final_total}, Downloaded: {final_downloaded}, "
          f"Skipped: {final_skipped}, Failed: {final_failed}")
    
    # Print summary
    print(f"\n✓ Extraction and download completed!")
    print(f"  Total posts: {final_total}")
    print(f"  Downloaded: {final_downloaded}")
    print(f"  Skipped (already exist): {final_skipped}")
    print(f"  Failed: {final_failed}")

