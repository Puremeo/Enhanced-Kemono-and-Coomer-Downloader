import os
import sys
import json
import requests
import re
from typing import Dict, List, Tuple, Optional, Any, Set
from tqdm import tqdm
from html.parser import HTMLParser
from urllib.parse import quote, urlparse, unquote

from .config import load_config, Config, get_domains
from .format_helpers import (
    sanitize_filename,
    sanitize_folder_name,
    sanitize_title,
    adapt_file_name,
    get_artist_dir,
)
from .failure_handlers import (
    FAILED_DOWNLOAD_LOG_FILENAME,
    load_failed_downloads,
    save_failed_downloads,
    add_failed_download,
    remove_failed_download,
)
from .session import cookie_map, headers
from .download_utils import download_with_resume


def ensure_directory(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


def load_profiles(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}


def save_profiles(path: str, profiles: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(profiles, file, indent=4)


def extract_data_from_link(link: str) -> Tuple[str, str, str, str]:
    """
    Extract service, user_id, and post_id from kemono and coomer links
    """
    # Get current domain mappings
    domains = get_domains()

    # Parse the URL to get the domain
    parsed_url = urlparse(link)
    domain = parsed_url.netloc

    # Determine which service this is based on domain
    if domain == domains["kemono"]:
        service_type = "kemono"
    elif domain == domains["coomer"]:
        service_type = "coomer"
    else:
        raise ValueError(
            f"Invalid domain: {domain}. Supported domains: {list(domains.values())}"
        )

    # Extract path components
    path_parts = parsed_url.path.strip("/").split("/")

    # Expected format: service/user/user_id/post/post_id
    if len(path_parts) < 5 or path_parts[1] != "user" or path_parts[3] != "post":
        raise ValueError(
            "Invalid link format. Expected: https://domain/service/user/user_id/post/post_id"
        )

    service = path_parts[0]
    user_id = path_parts[2]
    post_id = path_parts[4]

    return service_type, service, user_id, post_id


def get_api_base_url(domain_type: str) -> str:
    """
    Dynamically generate API base URL based on the domain type
    """
    domains = get_domains()
    domain = domains.get(domain_type)
    if not domain:
        raise ValueError(f"Unknown domain type: {domain_type}")
    return f"https://{domain}/api/v1/"


def fetch_profile(domain: str, service: str, user_id: str) -> Dict[str, Any]:
    """
    Fetch user profile with dynamic domain support
    """
    api_base_url = get_api_base_url(domain)
    url = f"{api_base_url}{service}/user/{user_id}/profile"
    
    # Get the actual domain name for cookie lookup
    domains = get_domains()
    actual_domain = domains.get(domain, domain)
    
    # Get cookies for this domain, fallback to empty dict if not found
    cookies = cookie_map.get(actual_domain, cookie_map.get(domain, {}))
    
    response = requests.get(url, cookies=cookies, headers=headers)
    response.raise_for_status()
    return response.json()


def fetch_post(domain: str, service: str, user_id: str, post_id: str) -> Dict[str, Any]:
    """
    Fetch post data with dynamic domain support
    """
    api_base_url = get_api_base_url(domain)
    url = f"{api_base_url}{service}/user/{user_id}/post/{post_id}"
    
    # Get the actual domain name for cookie lookup
    domains = get_domains()
    actual_domain = domains.get(domain, domain)
    
    # Get cookies for this domain, fallback to empty dict if not found
    cookies = cookie_map.get(actual_domain, cookie_map.get(domain, {}))
    
    response = requests.get(url, cookies=cookies, headers=headers)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.json()


class HTMLToMarkdown(HTMLParser):
    """Parser to convert HTML content to Markdown and plain text."""

    def __init__(self) -> None:
        super().__init__()
        self.result: List[str] = []
        self.raw_content: List[str] = []
        self.current_link: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href", "")
            self.current_link = href
            self.result.append("[")  # Markdown link opening
        elif tag in ("p", "br"):
            self.result.append("\n")  # New line for Markdown
        self.raw_content.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_link:
            self.result.append(f"]({self.current_link})")
            self.current_link = None
        self.raw_content.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        # Append visible text to the Markdown result
        if self.current_link:
            self.result.append(data.strip())
        else:
            self.result.append(data.strip())
        # Append all raw content for reference
        self.raw_content.append(data)

    def get_markdown(self) -> str:
        """Return the cleaned Markdown content."""
        return "".join(self.result).strip()

    def get_raw_content(self) -> str:
        """Return the raw HTML content."""
        return "".join(self.raw_content).strip()


def clean_html_to_text(html: str) -> Tuple[str, str]:
    """Converts HTML to Markdown and extracts raw HTML."""
    parser = HTMLToMarkdown()
    parser.feed(html)
    return parser.get_markdown(), parser.get_raw_content()



def download_files(
    file_list: List[Tuple[str, str]], folder_path: str, config: Config
) -> Dict[str, Any]:
    """
    Download files from a list of URLs and save them with unique names in the folder_path.
    Optimized with concurrent downloads and intelligent file skipping.

    :param file_list: List of tuples with original name and URL [(name, url), ...]
    :param folder_path: Directory to save downloaded files
    :param config: Configuration dictionary
    :return: Dictionary with download results {'success_count': int, 'failed_files': [{'name': str, 'url': str, 'error': str}]}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    seen_files: Set[str] = set()
    failed_files: List[Dict[str, str]] = []
    success_count: int = 0

    # Get valid domains for checking
    valid_domains = list(get_domains().values())
    
    # Filter out files that will be skipped to get accurate count
    files_to_process = []
    for idx, (original_name, url) in enumerate(file_list, start=1):
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        if all(valid_domain not in domain for valid_domain in valid_domains):
            continue
        
        # Derive file extension
        extension = ""
        if original_name and original_name.strip():
            extension = os.path.splitext(original_name)[1]
        if not extension:
            extension = os.path.splitext(parsed_url.path)[1] or ".bin"
        if extension == ".jpeg":
            extension = ".jpg"
        
        # Generate file name
        if not original_name or original_name.strip() == "":
            sanitized_name = str(idx)
        else:
            sanitized_name = adapt_file_name(original_name)
        file_name = f"{idx}-{sanitized_name}{extension}"
        
        if file_name in seen_files:
            continue
        seen_files.add(file_name)
        files_to_process.append((idx, original_name, url, file_name))
    
    # Get concurrent download workers from config
    max_workers = getattr(config, "download_max_workers", 5)
    verify_workers = getattr(config, "file_verify_workers", 10)
    strict_verify = getattr(config, "strict_file_verification", False)
    
    # Phase 1: Fast pre-check - batch check all files locally first
    files_to_verify = []  # Files that need remote verification
    files_to_download = []  # Files that need downloading
    skipped_count = 0
    
    if config.skip_existed_files:
        for idx, original_name, url, file_name in files_to_process:
            file_path = os.path.join(folder_path, file_name)
            part_path = file_path + ".part"
            part_exists = os.path.exists(part_path)
            
            # If .part file exists, always download (don't skip) - it's an incomplete download
            if part_exists:
                files_to_download.append((url, file_path, file_name))
                continue
            
            if os.path.exists(file_path):
                try:
                    existing_size = os.path.getsize(file_path)
                    if existing_size > 0 and not strict_verify:
                        # Fast skip: assume complete if file exists and has content
                        skipped_count += 1
                        continue
                    elif existing_size > 0 and strict_verify:
                        # Need to verify with remote server
                        files_to_verify.append((url, file_path, existing_size, file_name))
                    else:
                        # File exists but is empty, need to re-download
                        files_to_download.append((url, file_path, file_name))
                except OSError:
                    # Can't read file, need to download
                    files_to_download.append((url, file_path, file_name))
            else:
                # File doesn't exist, need to download
                files_to_download.append((url, file_path, file_name))
    else:
        # Skip checking if disabled
        for idx, original_name, url, file_name in files_to_process:
            file_path = os.path.join(folder_path, file_name)
            files_to_download.append((url, file_path, file_name))
    
    # Phase 2: Concurrently verify files that need remote size check
    if files_to_verify:
        def verify_file(url: str, file_path: str, existing_size: int, file_name: str) -> Tuple[bool, str, str]:
            """Verify if local file matches remote size. Returns (is_complete, url, file_path)"""
            try:
                response = requests.head(url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    expected_size = int(response.headers.get("content-length", 0))
                    if expected_size > 0 and existing_size == expected_size:
                        return True, url, file_path
                    elif expected_size > 0:
                        # Size mismatch, need to re-download
                        return False, url, file_path
                return False, url, file_path
            except Exception:
                # On error, assume need to download
                return False, url, file_path
        
        with ThreadPoolExecutor(max_workers=verify_workers) as verify_executor:
            verify_futures = {
                verify_executor.submit(verify_file, url, path, size, name): (url, path, name)
                for url, path, size, name in files_to_verify
            }
            
            for future in as_completed(verify_futures):
                url, path, name = verify_futures[future]
                try:
                    is_complete, _, _ = future.result()
                    if is_complete:
                        skipped_count += 1
                    else:
                        files_to_download.append((url, path, name))
                except Exception:
                    # On error, add to download list
                    files_to_download.append((url, path, name))
    
    # Phase 3: Concurrently download remaining files
    total_files = len(files_to_process)
    files_to_download_count = len(files_to_download)
    
    if files_to_download_count > 0:
        # Create overall progress bar
        overall_pbar = tqdm(
            total=files_to_download_count,
            desc="Downloading files",
            unit="file",
            position=0,
            leave=True,
            ncols=100,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} files [{elapsed}<{remaining}]'
        )
        
        def download_single_file(url: str, file_path: str, file_name: str) -> Tuple[bool, str, str]:
            """Download a single file. Returns (success, error_msg, file_name)"""
            try:
                parsed_url = urlparse(url)
                domain = parsed_url.netloc
                cookie_domain = "kemono" if "kemono" in domain else "coomer"
                success, error = download_with_resume(
                    url,
                    file_path,
                    headers=headers,
                    cookies=cookie_map.get(cookie_domain),
                    max_retries=getattr(config, 'download_retries', 5),
                    backoff_factor=getattr(config, 'download_backoff', 1.0),
                    chunk_size=8192,
                    show_progress=False,  # Disable individual progress bars when using overall bar
                )
                if success:
                    # Remove from failed downloads if successful
                    from .failure_handlers import remove_failed_download
                    remove_failed_download(url)
                else:
                    # Add to failed downloads if failed
                    from .failure_handlers import add_failed_download
                    add_failed_download(url)
                return success, error or "", file_name
            except Exception as err:
                # Add to failed downloads on exception
                from .failure_handlers import add_failed_download
                add_failed_download(url)
                return False, str(err), file_name
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(download_single_file, url, path, name): (url, path, name)
                for url, path, name in files_to_download
            }
            
            for future in as_completed(futures):
                url, path, name = futures[future]
                try:
                    success, error_msg, _ = future.result()
                    if success:
                        success_count += 1
                        overall_pbar.update(1)
                    else:
                        failed_files.append({"name": name, "url": url, "error": error_msg})
                        overall_pbar.update(1)
                except Exception as err:
                    failed_files.append({"name": name, "url": url, "error": str(err)})
                    overall_pbar.update(1)
        
        overall_pbar.close()
    else:
        overall_pbar = None
        if skipped_count > 0:
            print(f"All {total_files} files are already downloaded (skipped {skipped_count})")
    
    # Add skipped files to success count
    success_count += skipped_count

    return {
        "success_count": success_count,
        "failed_files": failed_files,
        "total_files": len(file_list),
    }


def save_post_info(
    post_data: Dict[str, Any], folder_path: str, file_format: str
) -> None:
    """
    Save post information to a file (title, content, polls, embeds, and file links).

    :param post_data: Dictionary containing post information
    :param folder_path: Path to save the info file
    :param file_format: File format ('md' or 'txt')
    """
    file_extension = ".md" if file_format == "md" else ".txt"
    file_name = f"files{file_extension}"
    file_path = os.path.join(folder_path, file_name)

    title, raw_title = clean_html_to_text(post_data["post"]["title"])
    content, raw_content = clean_html_to_text(post_data["post"]["content"])

    with open(file_path, "w", encoding="utf-8") as file:
        if file_format == "md":
            file.write(f"# {title}\n\n")
        else:
            file.write(f"Title: {title}\n\n")

        file.write(f"{content}\n\n")

        poll = post_data["post"].get("poll")
        if poll:
            if file_format == "md":
                file.write("## Poll Information\n\n")
                file.write(f"**Poll Title:** {poll.get('title', 'No Title')}\n")
                if poll.get("description"):
                    file.write(f"\n**Description:** {poll['description']}\n")
                file.write(
                    f"\n**Multiple Choices Allowed:** {'Yes' if poll.get('allows_multiple') else 'No'}\n"
                )
                file.write(f"**Started:** {poll.get('created_at', 'N/A')}\n")
                file.write(f"**Closes:** {poll.get('closes_at', 'N/A')}\n")
                file.write(f"**Total Votes:** {poll.get('total_votes', 0)}\n\n")

                file.write("### Choices and Votes\n\n")
                for choice in poll.get("choices", []):
                    file.write(
                        f"- **{choice['text']}:** {choice.get('votes', 0)} votes\n"
                    )
            else:
                file.write("Poll Information:\n\n")
                file.write(f"Poll Title: {poll.get('title', 'No Title')}\n")
                if poll.get("description"):
                    file.write(f"Description: {poll['description']}\n")
                file.write(
                    f"Multiple Choices Allowed: {'Yes' if poll.get('allows_multiple') else 'No'}\n"
                )
                file.write(f"Started: {poll.get('created_at', 'N/A')}\n")
                file.write(f"Closes: {poll.get('closes_at', 'N/A')}\n")
                file.write(f"Total Votes: {poll.get('total_votes', 0)}\n\n")

                file.write("Choices and Votes:\n")
                for choice in poll.get("choices", []):
                    file.write(f"- {choice['text']}: {choice.get('votes', 0)} votes\n")

            file.write("\n")

        embed = post_data["post"].get("embed")
        if embed:
            if file_format == "md":
                file.write("## Embedded Content\n")
            else:
                file.write("Embedded Content:\n")
            file.write(f"- URL: {embed.get('url', 'N/A')}\n")
            file.write(f"- Subject: {embed.get('subject', 'N/A')}\n")
            file.write(f"- Description: {embed.get('description', 'N/A')}\n")

        file.write("\n---\n\n")

        if file_format == "md":
            file.write("## Raw Title and Content\n\n")
        else:
            file.write("Raw Title and Content:\n\n")
        file.write(f"Raw Title: {raw_title}\n\n")
        file.write(f"Raw Content:\n{raw_content}\n\n")

        attachments = post_data.get("attachments", [])
        if attachments:
            if file_format == "md":
                file.write("## Attachments\n\n")
            else:
                file.write("Attachments:\n\n")
            for attach in attachments:
                server_url = f"{attach['server']}/data{attach['path']}?f={adapt_file_name(attach['name'])}"
                file.write(f"- {attach['name']}: {server_url}\n")

        videos = post_data.get("videos", [])
        if videos:
            if file_format == "md":
                file.write("## Videos\n\n")
            else:
                file.write("Videos:\n\n")
            for video in videos:
                server_url = f"{video['server']}/data{video['path']}?f={adapt_file_name(video['name'])}"
                file.write(f"- {video['name']}: {server_url}\n")

        images = []
        for preview in post_data.get("previews", []):
            if "name" in preview and "server" in preview and "path" in preview:
                server_url = f"{preview['server']}/data{preview['path']}"
                images.append((preview.get("name", ""), server_url))

        if images:
            if file_format == "md":
                file.write("## Images\n\n")
            else:
                file.write("Images:\n\n")
            for idx, (name, image_url) in enumerate(images, 1):
                if file_format == "md":
                    file.write(f"![Image {idx}]({image_url}) - {name}\n")
                else:
                    file.write(f"Image {idx}: {image_url} (Name: {name})\n")


def save_post_content(
    post_data: Dict[str, Any], folder_path: str, config: Config
) -> Dict[str, Any]:
    """
    Save post content and download files based on configuration settings.
    Now includes support for poll data if present.

    :param post_data: Dictionary containing post information
    :param folder_path: Path to save the post files
    :param config: Configuration dictionary with 'post_info' and 'save_info' keys

    :return: Dictionary with download results from download_files
    """
    ensure_directory(folder_path)

    if config.save_info:
        save_post_info(post_data, folder_path, config.post_info.lower())

    # Consolidate all files for download
    all_files_to_download = []

    for attach in post_data.get("attachments", []):
        if "name" in attach and "server" in attach and "path" in attach:
            url = f"{attach['server']}/data{attach['path']}?f={adapt_file_name(attach['name'])}"
            all_files_to_download.append((attach["name"], url))

    for video in post_data.get("videos", []):
        if "name" in video and "server" in video and "path" in video:
            url = f"{video['server']}/data{video['path']}?f={adapt_file_name(video['name'])}"
            all_files_to_download.append((video["name"], url))

    for image in post_data.get("previews", []):
        if "name" in image and "server" in image and "path" in image:
            url = f"{image['server']}/data{image['path']}"
            all_files_to_download.append((image.get("name", ""), url))

    # Remove duplicates based on URL
    unique_files_to_download = list(
        {url: (name, url) for name, url in all_files_to_download}.values()
    )

    # Download files to the specified folder and get results
    download_result = download_files(unique_files_to_download, folder_path, config)

    return download_result



def get_post_title(post_data: Dict[str, Any]) -> str:
    """
    Extract the post title from post_data.
    Return empty string if failed to get the title.
    Handles proper Unicode support.
    """
    try:
        title = post_data.get("post", {}).get("title", "")
        return sanitize_title(title)
    except Exception:
        return ""



def process_posts(links: List[str]) -> None:
    # Load configurations
    config = load_config()

    for user_link in links:
        try:
            print(f"\n--- Processing link: {user_link} ---")

            # Extract data from the link
            domain, service, user_id, post_id = extract_data_from_link(user_link)

            # Setup paths
            base_path = domain  # Use domain as base path (kemono or coomer)
            profiles_path = os.path.join(base_path, "profiles.json")

            ensure_directory(base_path)

            # Load existing profiles
            profiles = load_profiles(profiles_path)

            # Fetch and save profile if not already in profiles.json
            if user_id not in profiles:
                profile_data = fetch_profile(domain, service, user_id)
                profiles[user_id] = profile_data
                save_profiles(profiles_path, profiles)
            else:
                profile_data = profiles[user_id]

            # Create specific folder for the user
            user_name = profile_data.get("name", "unknown_user")
            artist_dir_name = get_artist_dir(user_name, service, user_id)
            user_folder = os.path.join(base_path, artist_dir_name)
            ensure_directory(user_folder)

            # Create posts folder and post-specific folder
            posts_folder = os.path.join(user_folder, "posts")
            ensure_directory(posts_folder)

            # Fetch post data
            post_data = fetch_post(domain, service, user_id, post_id)

            post_title = get_post_title(post_data)

            # Decide folder name based on config setting
            if config.post_folder_name == "title":
                # Check if old folder with just post_id exists and rename it
                old_folder_name = post_id
                old_post_folder = os.path.join(posts_folder, old_folder_name)
                
                # Prevent duplicated title
                folder_name = f"{post_id}_{post_title}"
                new_post_folder = os.path.join(posts_folder, folder_name)
                
                # If old folder exists and new folder doesn't, rename it
                if os.path.exists(old_post_folder) and not os.path.exists(new_post_folder):
                    try:
                        os.rename(old_post_folder, new_post_folder)
                        print(f"Renamed folder: {old_folder_name} -> {folder_name}")
                    except OSError as e:
                        print(f"Warning: Could not rename folder {old_folder_name}: {e}")
                        # If rename fails, use the old folder
                        folder_name = old_folder_name
            else:
                folder_name = post_id

            post_folder = os.path.join(posts_folder, folder_name)
            ensure_directory(post_folder)

            print(f"--- Post title: {post_title}")

            # Save post content using configurations
            download_result = save_post_content(post_data, post_folder, config)

            # Handle download results
            if download_result["failed_files"]:
                print(
                    f"\n⚠️ Link processed with {len(download_result['failed_files'])} failed downloads:",
                    f"{user_link}",
                    sep="\n",
                )
                print(
                    f"✅ Successfully downloaded: {download_result['success_count']}/{download_result['total_files']} files"
                )
                print("❌ Failed downloads:")
                for failed in download_result["failed_files"]:
                    print(f"  - {failed['name']}")

                add_failed_download(user_link)
                print(f"⚠️ Added link to {FAILED_DOWNLOAD_LOG_FILENAME}")
            else:
                print(f"\n✅ Link processed successfully: {user_link}")
                print(f"✅ Downloaded all {download_result['success_count']} files")

                remove_failed_download(user_link)
                print(f"✅ Removed link from {FAILED_DOWNLOAD_LOG_FILENAME}")

        except Exception as e:
            print(f"❌ Error processing link {user_link}: {e}")
            # Continue processing next links even if one fails
            continue
