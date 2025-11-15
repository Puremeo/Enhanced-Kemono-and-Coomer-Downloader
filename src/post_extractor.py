import os
import sys
import json
from pathlib import Path
from time import sleep
from queue import Queue
from threading import Event

import requests
from typing import Dict, List, Tuple, Optional, Any, Union, Callable, Iterator
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from requests import HTTPError

from .config import load_config, get_domains
from .format_helpers import sanitize_folder_name, get_artist_dir, sanitize_title
from .session import cookie_map, headers
import logging

import time as _time

logger = logging.getLogger(__name__)

TEMP_JSON = Path("temp_json")


def save_json(file_path: str, data: Any) -> None:
    """Helper function to save JSON files with UTF-8 encoding and pretty formatting"""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_base_config(profile_url: str) -> Tuple[str, str, str]:
    """
    Dynamically configure base URLs and directories based on the profile URL domain
    """
    # Extract domain from the profile URL
    domain = profile_url.split("/")[2]

    # Get valid domains
    domains = get_domains()
    valid_domains = list(domains.values())

    if domain not in valid_domains:
        raise ValueError(
            f"Unsupported domain: {domain}. Supported domains: {', '.join(valid_domains)}"
        )

    BASE_API_URL = f"https://{domain}/api/v1"
    BASE_SERVER = f"https://{domain}"

    # Determine base directory name from domain mapping
    if domain == domains["kemono"]:
        BASE_DIR = "kemono"
    elif domain == domains["coomer"]:
        BASE_DIR = "coomer"
    else:
        # Fallback to extracting from domain
        BASE_DIR = domain.split(".")[0]

    return BASE_API_URL, BASE_SERVER, BASE_DIR


def is_offset(value: str) -> bool:
    """Determine if the value is an offset (up to 5 digits) or an ID."""
    try:
        # Try to convert to integer and check the length
        return isinstance(int(value), int) and len(value) <= 5
    except ValueError:
        # If not a number, it's not an offset
        return False


def parse_fetch_mode(fetch_mode: str, total_count: int) -> List[Union[int, str]]:
    """
    Parse the fetch mode and return the corresponding offsets
    """
    # Special case: fetch all posts
    if fetch_mode == "all":
        return list(range(0, total_count, 50))

    # If it's a single number (specific page)
    if fetch_mode.isdigit():
        if is_offset(fetch_mode):
            return [int(fetch_mode)]
        else:
            # If it's a specific ID, return as such
            return ["id:" + fetch_mode]

    # If it's a range
    if "-" in fetch_mode:
        start, end = fetch_mode.split("-")

        # Handle "start" and "end" specifically
        if start == "start":
            start = 0
        else:
            start = int(start)

        if end == "end":
            end = total_count
        else:
            end = int(end)

        # If the values are offsets
        if start <= total_count and end <= total_count:
            # Calculate the number of pages needed to cover the range
            # Use ceil to ensure it includes the final page
            import math

            num_pages = math.ceil((end - start) / 50)

            # Generate list of offsets
            return [start + i * 50 for i in range(num_pages)]

        # If they appear to be IDs, return the ID range
        return ["id:" + str(start) + "-" + str(end)]

    raise ValueError(f"Invalid fetch mode: {fetch_mode}")


def get_artist_info(profile_url: str) -> Tuple[str, str]:
    # Extract service and user_id from URL
    parts = profile_url.split("/")
    service = parts[-3]
    user_id = parts[-1]
    return service, user_id


def fetch_user(base_api_url: str, service: str, domain: str, user_id: str, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    url = f"{base_api_url}/{service}/user/{user_id}/profile"
    last_exc = None
    for attempt in range(3):
        try:
            if session is not None:
                resp = session.get(url, timeout=30)
            else:
                resp = requests.get(url, cookies=cookie_map.get(domain, {}), headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_exc = e
            # Reduced delay for retries
            if attempt < 2:
                _time.sleep(0.5 * (attempt + 1))  # 0.5s, 1s instead of 1s, 2s
            continue
    raise last_exc


def fetch_post(
        base_api_url: str, domain: str, service: str, user_id: str, post_id: str, session: Optional[requests.Session] = None
) -> Dict[str, Any]:
    url = f"{base_api_url}/{service}/user/{user_id}/post/{post_id}"
    # Reduced delay: only sleep on retry, not on first attempt
    last_exc = None
    for attempt in range(4):
        try:
            if session is not None:
                resp = session.get(url, timeout=30)
            else:
                resp = requests.get(url, cookies=cookie_map.get(domain, {}), headers=headers, timeout=30)

            if resp.status_code == 403 and attempt < 3:
                _time.sleep(2 * (attempt + 1))  # 2s, 4s, 6s instead of 5s, 25s, 125s
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_exc = e
            # Only sleep on retry, with reduced delay
            if attempt < 3:
                _time.sleep(0.5 * (attempt + 1))  # 0.5s, 1s, 1.5s instead of 1s, 2s, 4s
            continue
    raise last_exc


def fetch_posts(
        base_api_url: str, domain: str, service: str, user_id: str, offset: int = 0, session: Optional[requests.Session] = None
) -> List[Dict[str, Any]]:
    if offset == 0:
        url = f"{base_api_url}/{service}/user/{user_id}/posts"
    else:
        url = f"{base_api_url}/{service}/user/{user_id}/posts?o={offset}"

    last_exc = None
    for attempt in range(3):
        try:
            if session is not None:
                resp = session.get(url, timeout=30)
            else:
                resp = requests.get(url, cookies=cookie_map.get(domain, {}), headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_exc = e
            # Reduced delay for retries
            if attempt < 2:
                _time.sleep(0.5 * (attempt + 1))  # 0.5s, 1s instead of 1s, 2s
            continue
    raise last_exc


def save_json_incrementally(
    file_path: str, new_posts: List[Dict[str, Any]], start_offset: int, end_offset: int
) -> None:
    # Create a new dictionary with current posts
    data = {"total_posts": len(new_posts), "posts": new_posts}

    # Save the new file, replacing the existing one
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def process_posts(
        base_api_url: str,
        domain: str,
        posts: List[Dict[str, Any]],
        page_number: int,
        offset: int,
        base_server: str,
        save_empty_files: bool = True,
        id_filter: Optional[Callable[[str], bool]] = None,
) -> List[Dict[str, Any]]:
    # Process posts and organize file links
    not_done = []
    processed = []
    for post in posts:
        original_post = post
        local_post_json = TEMP_JSON / post["user"] / (post["id"] + ".json")
        if local_post_json.exists():
            with local_post_json.open() as fr:
                post = json.load(fr)
        else:
            try:
                post = fetch_post(base_api_url, domain, post["service"], post["user"], post["id"])
            except HTTPError as err:
                print("Rate limited {} - {}".format(post["user"], post["id"]))
                not_done.append(original_post)
                continue
            with local_post_json.open("w") as fw:
                json.dump(post, fw)
        previews = post["previews"]
        post = post["post"]
        # ID filter if specified
        if id_filter and not id_filter(post["id"]):
            continue

        result = {
            "id": post["id"],
            "user": post["user"],
            "service": post["service"],
            "title": post["title"],
            "link": f"{base_server}/{post['service']}/user/{post['user']}/post/{post['id']}",
            "page": page_number,
            "offset": offset,
            "files": [],
        }

        # Combine previews, top-level attachments/videos, and inner post attachments into a single list for searching
        top_level_attachments = []
        # The wrapper JSON (from temp_json) may contain attachments/videos at the top level
        try:
            wrapper = None
            # attempt to read a wrapper file if it exists in TEMP_JSON
            wrapper_path = TEMP_JSON / post["user"] / (post["id"] + ".json")
            if wrapper_path.exists():
                with wrapper_path.open("r", encoding="utf-8") as wf:
                    wrapper = json.load(wf)
            # If wrapper contains top-level attachments or videos, include them
            if isinstance(wrapper, dict):
                if isinstance(wrapper.get("attachments"), list):
                    top_level_attachments.extend(wrapper.get("attachments"))
                if isinstance(wrapper.get("videos"), list):
                    # videos entries may contain server/path fields
                    top_level_attachments.extend(wrapper.get("videos"))
        except Exception:
            # ignore issues reading wrapper; fall back to inner attachments only
            top_level_attachments = []

        inner_attachments = post.get("attachments", []) or []
        all_data = (previews or []) + top_level_attachments + inner_attachments

        # Process files in the file field
        if "file" in post and post["file"]:
            matching_data = next(
                (item for item in all_data if item["path"] == post["file"]["path"]),
                None,
            )
            if matching_data:
                file_url = f"{matching_data['server']}/data{post['file']['path']}"
                if file_url not in [f["url"] for f in result["files"]]:
                    result["files"].append(
                        {"name": post["file"]["name"], "url": file_url}
                    )

        # Process files in the attachments field
        for attachment in post.get("attachments", []):
            matching_data = next(
                (item for item in all_data if item.get("path") == attachment.get("path")), None
            )
            if not matching_data:
                logger.debug("No matching attachment data for %s - %s", post.get("user"), attachment.get("path"))
                continue

            # Ensure matching_data contains required fields
            server = matching_data.get("server")
            path = attachment.get("path")
            if not server or not path:
                logger.warning("Malformed data %s - %s attachment %s", post.get("user"), post.get("id"), attachment.get("path"))
                # skip this attachment but continue processing others
                continue

            file_url = f"{server}/data{path}"
            if file_url not in [f.get("url") for f in result.get("files", [])]:
                result["files"].append({"name": attachment.get("name"), "url": file_url})
        # Ignore posts without files if save_empty_files is False
        if not save_empty_files and not result["files"]:
            continue

        processed.append(result)

    if len(not_done) > 0:
        logger.warning("%d posts skipped due to rate limit; processed %d posts", len(not_done), len(processed))

    return processed


def extract_posts(profile_url: str, fetch_mode: str = "all") -> str:
    """
    Return the full path of the generated JSON file with process post data
    """

    # Load configuration from JSON file
    config = load_config()

    # Get the value of 'get_empty_posts' from configuration
    SAVE_EMPTY_FILES = config.get_empty_posts

    # Configure base URLs dynamically
    BASE_API_URL, BASE_SERVER, BASE_DIR = get_base_config(profile_url)

    # Base folder
    base_dir = BASE_DIR
    # domain should be the hostname (e.g., coomer.st) for cookie lookups
    domain = profile_url.split("/")[2]
    os.makedirs(base_dir, exist_ok=True)

    # Update the profiles.json file
    profiles_file = os.path.join(base_dir, "profiles.json")
    if os.path.exists(profiles_file):
        with open(profiles_file, "r", encoding="utf-8") as f:
            profiles = json.load(f)
    else:
        profiles = {}

    # Fetch first set of posts for general information
    service, user_id = get_artist_info(profile_url)
    user_data = fetch_user(BASE_API_URL, service, domain, user_id)
    name = user_data["name"]
    count = user_data["post_count"]

    # Save artist information
    artist_info = {
        "id": user_id,
        "name": name,
        "service": service,
        "indexed": user_data["indexed"],
        "updated": user_data["updated"],
        "public_id": user_data["public_id"],
        "relation_id": user_data["relation_id"],
    }
    profiles[user_id] = artist_info
    save_json(profiles_file, profiles)
    (TEMP_JSON / user_id).mkdir(parents=True, exist_ok=True)

    # Artist folder
    artist_dir_name = get_artist_dir(name, service, user_id)
    artist_dir = os.path.join(base_dir, artist_dir_name)
    os.makedirs(artist_dir, exist_ok=True)

    # Process fetch mode
    today = datetime.now().strftime("%Y-%m-%d")

    # If no posts, create an empty posts JSON and return
    if count == 0:
        file_path = os.path.join(artist_dir, f"posts-0-0-{today}.json")
        save_json_incrementally(file_path, [], 0, 0)
        return os.path.abspath(file_path)

    try:
        offsets = parse_fetch_mode(fetch_mode, count)
    except ValueError as e:
        print(e)
        return

    # Check if it's a search for specific ID
    id_filter = None
    found_ids = set()
    if isinstance(offsets[0], str) and offsets[0].startswith("id:"):
        # Extract IDs for filter
        id_range = offsets[0].split(":")[1]

        if "-" in id_range:
            id1, id2 = map(str, sorted(map(int, id_range.split("-"))))
            id_filter = lambda x: id1 <= str(x) <= id2
        else:
            id_filter = lambda x: x == id_range

        # Redefine offsets to scan all pages
        offsets = list(range(0, count, 50))

    # JSON filename with offset range
    if len(offsets) > 1:
        file_path = os.path.join(
            artist_dir, f"posts-{offsets[0]}-{offsets[-1]}-{today}.json"
        )
    else:
        file_path = os.path.join(artist_dir, f"posts-{offsets[0]}-{today}.json")

    new_posts = []
    # Main processing
    for offset in offsets:
        page_number = (offset // 50) + 1
        post_data = fetch_posts(BASE_API_URL, domain, service, user_id, offset=offset)

        processed_posts = process_posts(
            BASE_API_URL,
            domain,
            post_data,
            page_number,
            offset,
            BASE_SERVER,
            save_empty_files=SAVE_EMPTY_FILES,
            id_filter=id_filter,
        )
        new_posts.extend(processed_posts)
        # Save incremental posts to JSON
        if processed_posts:
            save_json_incrementally(file_path, new_posts, offset, offset + 50)

            # Check if found the desired IDs
            if id_filter:
                found_ids.update(post["id"] for post in processed_posts)

                # Check if found both IDs
                if (id1 in found_ids) and (id2 in found_ids):
                    print(f"Found both IDs: {id1} and {id2}")
                    break

    return os.path.abspath(file_path)


def extract_posts_streaming(profile_url: str, fetch_mode: str = "all") -> Iterator[Dict[str, Any]]:
    """
    Extract posts in streaming mode, yielding posts as they are processed.
    This allows downloading to start while extraction is still in progress.
    
    Yields:
        Dict containing post data with 'id', 'user', 'service', 'title', 'link', 'files', etc.
    """
    # Load configuration
    config = load_config()
    SAVE_EMPTY_FILES = config.get_empty_posts

    # Configure base URLs dynamically
    BASE_API_URL, BASE_SERVER, BASE_DIR = get_base_config(profile_url)

    # Base folder
    base_dir = BASE_DIR
    domain = profile_url.split("/")[2]
    os.makedirs(base_dir, exist_ok=True)

    # Update the profiles.json file
    profiles_file = os.path.join(base_dir, "profiles.json")
    if os.path.exists(profiles_file):
        with open(profiles_file, "r", encoding="utf-8") as f:
            profiles = json.load(f)
    else:
        profiles = {}

    # Fetch first set of posts for general information
    service, user_id = get_artist_info(profile_url)
    user_data = fetch_user(BASE_API_URL, service, domain, user_id)
    name = user_data["name"]
    count = user_data["post_count"]

    # Save artist information
    artist_info = {
        "id": user_id,
        "name": name,
        "service": service,
        "indexed": user_data["indexed"],
        "updated": user_data["updated"],
        "public_id": user_data["public_id"],
        "relation_id": user_data["relation_id"],
    }
    profiles[user_id] = artist_info
    save_json(profiles_file, profiles)
    (TEMP_JSON / user_id).mkdir(parents=True, exist_ok=True)

    # Artist folder
    artist_dir_name = get_artist_dir(name, service, user_id)
    artist_dir = os.path.join(base_dir, artist_dir_name)
    os.makedirs(artist_dir, exist_ok=True)

    # Process fetch mode
    try:
        offsets = parse_fetch_mode(fetch_mode, count)
    except ValueError as e:
        print(e)
        return

    # Check if it's a search for specific ID
    id_filter = None
    found_ids = set()
    if isinstance(offsets[0], str) and offsets[0].startswith("id:"):
        id_range = offsets[0].split(":")[1]
        if "-" in id_range:
            id1, id2 = map(str, sorted(map(int, id_range.split("-"))))
            id_filter = lambda x: id1 <= str(x) <= id2
        else:
            id_filter = lambda x: x == id_range
        offsets = list(range(0, count, 50))

    # Main processing - yield posts as they are processed
    for offset in offsets:
        page_number = (offset // 50) + 1
        post_data = fetch_posts(BASE_API_URL, domain, service, user_id, offset=offset)

        processed_posts = process_posts(
            BASE_API_URL,
            domain,
            post_data,
            page_number,
            offset,
            BASE_SERVER,
            save_empty_files=SAVE_EMPTY_FILES,
            id_filter=id_filter,
        )
        
        # Yield each processed post immediately
        for post in processed_posts:
            yield post
            
            # Check if found the desired IDs
            if id_filter:
                found_ids.add(post["id"])
                if (id1 in found_ids) and (id2 in found_ids):
                    print(f"Found both IDs: {id1} and {id2}")
                    return
