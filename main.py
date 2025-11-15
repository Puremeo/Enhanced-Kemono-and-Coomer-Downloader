import os
import sys
import subprocess
import re
import json
import time
import importlib
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse


def install_requirements() -> None:
    """Verify and install dependencies from requirements.txt."""
    requirements_file = "requirements.txt"

    if not os.path.exists(requirements_file):
        print(f"Error: File {requirements_file} not found.")
        return

    with open(requirements_file, "r", encoding="utf-8") as req_file:
        for line in req_file:
            # Read each line, ignore empty or comments
            package = line.strip()
            if package and not package.startswith("#"):
                try:
                    # Try to import the package to check if it's already installed
                    package_name = package.split("==")[
                        0
                    ]  # Ignore specific version when importing
                    importlib.import_module(package_name)
                except ImportError:
                    # If it fails, install the package using pip
                    print(f"Installing the package: {package}")
                    try:
                        subprocess.check_call(
                            [sys.executable, "-m", "pip", "install", package],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        # Try alternative pip installation methods
                        try:
                            subprocess.check_call(
                                ["pip", "install", package],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL
                            )
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            print(f"Warning: Could not install {package}. Please install manually: pip install {package}")


# Import src modules - use try-except to handle missing dependencies
try:
    from src.format_helpers import sanitize_title
    from src.post_extractor import extract_posts
    from src.post_downloader import process_posts
    from src.batch_file_downloader import batch_download_posts
    from src.config import load_config, save_config, Config, get_domains
    from src.session import (
        create_session,
        save_api_token,
        login_with_form,
        login_with_api,
        save_credentials,
        login_with_saved_credentials,
        clear_saved_credentials,
    )
    from src.favorites_downloader import download_favorites
except ImportError as e:
    # If import fails, dependencies will be installed in main block
    # This is just to avoid NameError during function definitions
    # The actual imports will happen after install_requirements() in main block
    pass


def clear_screen() -> None:
    """Clear console screen in a cross-platform compatible way"""
    os.system("cls" if os.name == "nt" else "clear")


def display_logo() -> None:
    """Display the project logo"""
    logo = r"""
 _  __                                                   
| |/ /___ _ __ ___   ___  _ __   ___                     
| ' // _ \ '_ ` _ \ / _ \| '_ \ / _ \                    
| . \  __/ | | | | | (_) | | | | (_) |                   
|_|\_\___|_| |_| |_|\___/|_| |_|\___/                    
 / ___|___   ___  _ __ ___   ___ _ __                    
| |   / _ \ / _ \| '_ ` _ \ / _ \ '__|                   
| |__| (_) | (_) | | | | | |  __/ |                      
 \____\___/ \___/|_| |_| |_|\___|_|          _           
|  _ \  _____      ___ __ | | ___   __ _  __| | ___ _ __ 
| | | |/ _ \ \ /\ / / '_ \| |/ _ \ / _` |/ _` |/ _ \ '__|
| |_| | (_) \ V  V /| | | | | (_) | (_| | (_| |  __/ |   
|____/ \___/ \_/\_/ |_| |_|_|\___/ \__,_|\__,_|\___|_|   

Project Repository: https://github.com/isaswa/Better-Kemono-and-Coomer-Downloader
Modified from: Kemono-and-Coomer-Downloader by e43b
License: MIT License
"""
    print(logo)


def normalize_path(path: str) -> str:
    """
    Normalize file path to handle non-ASCII characters
    """
    try:
        # If the original path exists, return it
        if os.path.exists(path):
            return path

        # Extract the filename and path components
        filename = os.path.basename(path)
        path_parts = path.split(os.sep)

        # Identify if searching in kemono or coomer
        base_dir = None
        if "kemono" in path_parts:
            base_dir = "kemono"
        elif "coomer" in path_parts:
            base_dir = "coomer"

        if base_dir:
            # Search in all subdirectories of the base directory
            for root, dirs, files in os.walk(base_dir):
                if filename in files:
                    return os.path.join(root, filename)

        # If still not found, try the normalized path
        return os.path.abspath(os.path.normpath(path))

    except Exception as e:
        print(f"Error when normalizing path: {e}")
        return path


def run_download_script(json_path: str) -> None:
    """Run the download script with the generated JSON and do detailed real-time tracking"""
    try:
        # Normalize the JSON path
        json_path = normalize_path(json_path)

        # Check if the JSON file exists
        if not os.path.exists(json_path):
            print(f"Error: JSON file not found: {json_path}")
            return

        # Read configurations
        config = load_config()

        # Read the posts JSON
        with open(json_path, "r", encoding="utf-8") as posts_file:
            posts_data = json.load(posts_file)

        # Initial analysis
        total_posts = posts_data["total_posts"]
        post_ids = [post["id"] for post in posts_data["posts"]]

        # File count
        total_files = sum(len(post["files"]) for post in posts_data["posts"])

        # Print initial information
        print(f"Post extraction completed: {total_posts} posts found")
        print(f"Total number of files to download: {total_files}")
        print("Starting post downloads")

        # Determine processing order
        if config.process_from_oldest:
            post_ids = sorted(post_ids)  # Order from oldest to newest
        else:
            post_ids = sorted(post_ids, reverse=True)  # Order from newest to oldest

        # Base folder for posts using path normalization
        posts_folder = normalize_path(os.path.join(os.path.dirname(json_path), "posts"))
        os.makedirs(posts_folder, exist_ok=True)

        # Process each post
        for idx, post_id in enumerate(post_ids, 1):
            # Find specific post data
            post_data = next(
                (p for p in posts_data["posts"] if p["id"] == post_id), None
            )

            if post_data:
                # Specific post folder with normalization
                # Determine folder name based on config
                if config.post_folder_name == "title":
                    # Extract title from post data
                    post_title = post_data.get("title", "").strip()
                    if post_title:
                        sanitized_title = sanitize_title(post_title)
                        folder_name = f"{post_id}_{sanitized_title}"
                    else:
                        folder_name = post_id
                else:
                    folder_name = post_id

                post_folder = normalize_path(os.path.join(posts_folder, folder_name))
                os.makedirs(post_folder, exist_ok=True)

                # Count number of files in JSON for this post
                expected_files_count = len(post_data["files"])

                # Count existing files in the folder
                existing_files = [
                    f
                    for f in os.listdir(post_folder)
                    if os.path.isfile(os.path.join(post_folder, f))
                ]
                existing_files_count = len(existing_files)

                # If all files exist, skip the download
                if existing_files_count == expected_files_count:
                    continue

                try:
                    batch_download_posts(json_path, post_id)

                    # After download, check files again
                    current_files = [
                        f
                        for f in os.listdir(post_folder)
                        if os.path.isfile(os.path.join(post_folder, f))
                    ]
                    current_files_count = len(current_files)

                    # Check download result
                    if current_files_count == expected_files_count:
                        print(
                            f"Post {post_id} downloaded completely ({current_files_count}/{expected_files_count} files)"
                        )
                    else:
                        print(
                            f"Post {post_id} partially downloaded: {current_files_count}/{expected_files_count} files"
                        )

                except FileNotFoundError as e:
                    print(f"Error: JSON file not found for post {post_id}: {e}")
                except Exception as e:
                    print(f"Error while downloading post {post_id}: {e}")

                # Small delay to avoid overload
                time.sleep(0.5)

        print("\nAll posts have been processed!")

    except Exception as e:
        print(f"Unexpected error: {e}")
        # Add more details for diagnosis
        import traceback

        traceback.print_exc()


def download_specific_posts() -> None:
    """Option to download specific posts"""
    clear_screen()
    display_logo()
    print("Download 1 post or a few separate posts")
    print("------------------------------------")
    print("Choose the input method:")
    print("1 - Enter the links directly")
    print("2 - Loading links from a TXT file")
    print("3 - Restart failed downloads in previous attempts")
    print("4 - Back to the main menu")
    choice = input("\nEnter your choice (1/2/3/4): ")

    links: List[str] = []

    if choice == "4":
        return
    elif choice == "1":
        print("Paste the links to the posts (separated by commas or space):")
        content = input("Links: ")
        links = re.split(r"[,\s]+", content)
    elif choice == "2":
        file_path = input("Enter the path to the TXT file: ").strip()
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
                # Split by comma, space, or linebreak
                links = re.split(r"[,\s\n]+", content)
        else:
            print(f"Error: The file '{file_path}' was not found.")
            input("\nPress Enter to continue...")
            return
    elif choice == "3":
        failed_downloads_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "failed_downloads.txt"
        )
        if os.path.exists(failed_downloads_path):
            with open(failed_downloads_path, "r", encoding="utf-8") as file:
                content = file.read()
                links = re.split(r"[,\s\n]+", content)
                links = [link.strip() for link in links if link.strip()]
                if links:
                    print(f"Found {len(links)} failed download(s) to retry.")
                else:
                    print("No failed downloads found in failed_downloads.txt")
                    input("\nPress Enter to continue...")
                    return
        else:
            print("failed_downloads.txt file not found. No failed downloads to retry.")
            input("\nPress Enter to continue...")
            return
    else:
        print("Invalid option. Return to the previous menu.")
        input("\nPress Enter to continue...")
        return

    links = [link.strip() for link in links if link.strip()]

    # Get current valid domains
    valid_domains = list(get_domains().values())
    
    # Filter valid links
    valid_links = []
    for link in links:
        try:
            domain = urlparse(link).netloc
            if domain in valid_domains:
                valid_links.append(link)
            else:
                print(f"Domain not supported: {domain}")
                print(f"Supported domains: {', '.join(valid_domains)}")
        except IndexError:
            print(f"Link format error: {link}")
        except Exception as e:
            print(f"Error validating link {link}: {e}")
    
    if not valid_links:
        print("No valid links to process.")
        input("\nPress Enter to continue...")
        return
    
    # Ask user if they want concurrent processing
    config = load_config()
    use_concurrent = getattr(config, "use_concurrent_post_processing", True)
    if len(valid_links) > 1:
        concurrent_choice = input(f"Process {len(valid_links)} links concurrently? (Y/n): ").strip().lower()
        use_concurrent = concurrent_choice != "n"
    
    if use_concurrent and len(valid_links) > 1:
        # Concurrent processing for multiple links
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = getattr(config, "concurrent_post_workers", 3)
        
        print(f"\nProcessing {len(valid_links)} links concurrently (using {max_workers} workers)...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_posts, [link]): link for link in valid_links}
            
            for future in as_completed(futures):
                link = futures[future]
                try:
                    future.result()
                    print(f"✓ Completed: {link}")
                except Exception as e:
                    print(f"❌ Error processing link {link}: {e}")
        
        print(f"\n✓ All {len(valid_links)} links processed!")
    else:
        # Sequential processing (original behavior)
        for link in valid_links:
            try:
                process_posts([link])
            except Exception as e:
                print(f"Error downloading the post: {link}")
                print(str(e))

    input("\nPress Enter to continue...")


def download_profile_posts() -> None:
    """Option to download posts from a profile"""
    clear_screen()
    display_logo()
    print("Download Profile Posts")
    print("-----------------------")
    print("1 - Download all posts from a profile")
    print("2 - Download posts from a specific page")
    print("3 - Downloading posts from a range of pages")
    print("4 - Downloading posts between two specific posts")
    print("5 - Back to the main menu")

    choice = input("\nEnter your choice (1/2/3/4/5): ")

    if choice == "5":
        return

    profile_link = input("Paste the profile link: ")
    
    # Ask user if they want parallel mode
    config = load_config()
    use_parallel = getattr(config, "use_parallel_extract_download", True)
    if use_parallel:
        parallel_choice = input("Use parallel mode (extract and download simultaneously)? (Y/n): ").strip().lower()
        use_parallel = parallel_choice != "n"

    try:
        if use_parallel:
            # Use parallel extraction and download
            from src.parallel_extract_download import extract_and_download_parallel
            
            fetch_mode = "all"
            if choice == "2":
                page = input("Enter the page number (0 = first page, 50 = second, etc.): ")
                fetch_mode = page
            elif choice == "3":
                start_page = input("Enter the start page (start, 0, 50, 100, etc.): ")
                end_page = input("Enter the final page (or use end, 300, 350, 400): ")
                fetch_mode = f"{start_page}-{end_page}"
            elif choice == "4":
                first_post = input("Paste the link or ID of the first post: ")
                second_post = input("Paste the link or ID from the second post: ")
                first_id = first_post.split("/")[-1] if "/" in first_post else first_post
                second_id = second_post.split("/")[-1] if "/" in second_post else second_post
                fetch_mode = f"{first_id}-{second_id}"
            
            try:
                extract_and_download_parallel(profile_link, fetch_mode)
            except Exception as e:
                print(f"Error in parallel processing: {e}")
                import traceback
                traceback.print_exc()
        else:
            # Use traditional mode (extract first, then download)
            json_path: Optional[str] = None

            if choice == "1":
                try:
                    print("Processing profile...")
                    json_path = extract_posts(profile_link, "all")
                except Exception as e:
                    print(f"Error generating JSON: {e}")
                    json_path = None

            elif choice == "2":
                page = input("Enter the page number (0 = first page, 50 = second, etc.): ")
                try:
                    json_path = extract_posts(profile_link, page)
                except Exception as e:
                    print(f"Error generating JSON: {e}")
                    json_path = None

            elif choice == "3":
                start_page = input("Enter the start page (start, 0, 50, 100, etc.): ")
                end_page = input("Enter the final page (or use end, 300, 350, 400): ")
                try:
                    json_path = extract_posts(profile_link, f"{start_page}-{end_page}")
                except Exception as e:
                    print(f"Error generating JSON: {e}")
                    json_path = None

            elif choice == "4":
                first_post = input("Paste the link or ID of the first post: ")
                second_post = input("Paste the link or ID from the second post: ")

                first_id = first_post.split("/")[-1] if "/" in first_post else first_post
                second_id = (
                    second_post.split("/")[-1] if "/" in second_post else second_post
                )

                try:
                    json_path = extract_posts(profile_link, f"{first_id}-{second_id}")
                except Exception as e:
                    print(f"Error generating JSON: {e}")
                    json_path = None

            if json_path:
                run_download_script(json_path)
            else:
                print("The JSON path could not be found.")

    except Exception as e:
        print(f"Error in profile processing: {e}")
        import traceback
        traceback.print_exc()

    input("\nPress Enter to continue...")


def customize_settings() -> None:
    """Option to customize settings"""
    config_path = os.path.join("config", "conf.json")
    config: Config = load_config()
    while True:
        clear_screen()
        display_logo()
        print("Customize Settings")
        print("------------------------")
        print(f"1 - Take empty posts: {config.get_empty_posts}")
        print(f"2 - Download older posts first: {config.process_from_oldest}")
        print(
            f"3 - For individual posts, create a file with information (title, description, etc.): {config.save_info}"
        )
        print(
            f"4 - Choose the type of file to save the information (Markdown or TXT): {config.post_info}"
        )
        print(
            f"5 - Skip already downloaded files when processing links (recommended: True): {config.skip_existed_files}"
        )
        print("6 - Back to the main menu")
        print("7 - Authentication (set API token or login)")

        choice = input("\nChoose an option (1/2/3/4/5/6/7): ")

        if choice == "1":
            config.get_empty_posts = not config.get_empty_posts
        elif choice == "2":
            config.process_from_oldest = not config.process_from_oldest
        elif choice == "3":
            config.save_info = not config.save_info
        elif choice == "4":
            config.post_info = "txt" if config.post_info == "md" else "md"
        elif choice == "5":
            config.skip_existed_files = not config.skip_existed_files
        elif choice == "6":
            break
        elif choice == "7":
            # Authentication submenu
            clear_screen()
            display_logo()
            print("Authentication settings")
            print("1 - Set API token (preferred)")
            print("2 - Login with username/password (save cookies)")
            print("3 - Back")
            sub = input("Choose option (1/2/3): ").strip()
            if sub == "1":
                token = input("Paste your Coomer API token: ").strip()
                if token:
                    try:
                        save_api_token(token, os.path.join("config", "conf.json"))
                        print("API token saved to config/conf.json")
                    except Exception as e:
                        print(f"Failed to save API token: {e}")
                input("Press Enter to continue...")
            elif sub == "2":
                # Authentication via username/password or saved credentials
                domains = get_domains()
                default_domain = domains.get("coomer") or "https://coomer.st"
                print(f"Using domain: {default_domain}")
                print("1 - Enter username/password now and optionally save them")
                print("2 - Attempt login using saved credentials")
                print("3 - Clear saved credentials")
                print("4 - Back")
                auth_choice = input("Choose option (1/2/3/4): ").strip()
                if auth_choice == "1":
                    username = input("Username or email: ").strip()
                    password = input("Password: ").strip()
                    save_choice = input("Save these credentials to config for future use? (y/N): ").strip().lower()
                    if not username or not password:
                        print("Username/password cannot be empty")
                        input("Press Enter to continue...")
                    else:
                        print("Attempting login via API...")
                        success = False
                        try:
                            # Try API login first (preferred method)
                            sess = login_with_api(username, password, domain=default_domain, save_cookie=True)
                            print("✓ Login successful! Cookies saved to config/conf.json")
                            success = True
                        except Exception as api_error:
                            # Fall back to form-based login
                            print(f"API login failed: {api_error}")
                            print("Trying form-based login as fallback...")
                            login_path = "/users/sign_in"
                            payloads = [
                                {"email": username, "password": password},
                                {"user[email]": username, "user[password]": password},
                                {"username": username, "password": password},
                            ]
                            for payload in payloads:
                                try:
                                    sess = login_with_form(login_path, payload, domain=default_domain, save_cookie=True)
                                    print("✓ Login successful! Cookies saved to config/conf.json")
                                    success = True
                                    break
                                except Exception:
                                    continue
                        
                        if success and save_choice == "y":
                            # save credentials to config
                            try:
                                save_credentials(username, password, os.path.join("config", "conf.json"))
                                print("Credentials saved to config/conf.json")
                            except Exception as e:
                                print(f"Failed to save credentials: {e}")
                        if not success:
                            print("❌ Login failed. Please check your username and password.")
                        input("Press Enter to continue...")
                elif auth_choice == "2":
                    try:
                        sess = login_with_saved_credentials(domain=default_domain, save_cookie=True)
                        if sess:
                            print("Login with saved credentials succeeded; cookies saved to config/conf.json")
                        else:
                            print("No saved credentials found. Please add them first.")
                    except Exception as e:
                        print(f"Login with saved credentials failed: {e}")
                    input("Press Enter to continue...")
                elif auth_choice == "3":
                    clear_saved_credentials(os.path.join("config", "conf.json"))
                    print("Saved credentials cleared from config/conf.json")
                    input("Press Enter to continue...")
                else:
                    # Back or invalid
                    pass
            else:
                # Back
                pass
        else:
            print("Invalid option. Please try again.")

        # Persist changes after each action
        try:
            save_config(config, config_path)
            print("\nUpdated configurations.")
        except Exception:
            print("Failed to save configuration.")

        time.sleep(1)


def _handle_cli_args():
    """Handle non-interactive CLI args. Usage: --download-favorites [target_dir]"""
    if "--download-favorites" in sys.argv:
        idx = sys.argv.index("--download-favorites")
        target = None
        if len(sys.argv) > idx + 1:
            target = sys.argv[idx + 1]
        print("Starting favorites download to:", target or "./coomer")
        download_favorites(download_dir=target)
        sys.exit(0)

def main_menu() -> None:
    """Application main menu"""
    create_session()
    while True:
        clear_screen()
        display_logo()
        print("Choose an option:")
        print("1 - Download 1 post or a few separate posts")
        print("2 - Download all posts from a profile")
        print("3 - Customize the program settings")
        print("4 - Exit the program")
        print("5 - Download all favorite accounts (从收藏列表批量下载)")

        choice = input("\nEnter your choice (1/2/3/4): ")

        if choice == "1":
            download_specific_posts()
        elif choice == "2":
            download_profile_posts()
        elif choice == "3":
            customize_settings()
        elif choice == "5":
            # Interactive favorites download
            clear_screen()
            display_logo()
            print("Download favorite accounts")
            print("--------------------------")
            target_dir = input("Target download directory (default: ./coomer): ").strip() or "coomer"
            limit_input = input("Max accounts to download (enter for no limit): ").strip()
            try:
                limit = int(limit_input) if limit_input else None
            except ValueError:
                print("Invalid limit, proceeding with no limit.")
                limit = None
            
            # Ask if user wants parallel mode
            cfg = load_config()
            use_parallel = getattr(cfg, "use_parallel_extract_download", True)
            if use_parallel:
                parallel_choice = input("Use parallel mode (extract and download simultaneously for each account)? (Y/n): ").strip().lower()
                use_parallel = parallel_choice != "n"
            
            # Save temporary limit to config for this run
            if limit:
                cfg.favorites_limit = limit
            save_config(cfg, os.path.join("config", "conf.json"))
            print(f"Starting favorites download to {target_dir} (limit={limit}, parallel={use_parallel})")
            try:
                download_favorites(download_dir=target_dir, use_parallel=use_parallel)
            except Exception as e:
                print(f"Favorites download failed: {e}")
                import traceback
                traceback.print_exc()
            input("\nPress Enter to return to menu...")
        elif choice == "4":
            print("Leaving the program. See you later!")
            break
        else:
            input("Invalid option. Press Enter to continue...")


if __name__ == "__main__":
    print("Checking dependencies...")
    install_requirements()
    print("Verified dependencies.\n")
    
    # Re-import src modules after dependencies are installed (in case initial import failed)
    try:
        from src.format_helpers import sanitize_title
        from src.post_extractor import extract_posts
        from src.post_downloader import process_posts
        from src.batch_file_downloader import batch_download_posts
        from src.config import load_config, save_config, Config, get_domains
        from src.session import (
            create_session,
            save_api_token,
            login_with_form,
            login_with_api,
            save_credentials,
            login_with_saved_credentials,
            clear_saved_credentials,
        )
        from src.favorites_downloader import download_favorites
    except ImportError as e:
        print(f"Error: Failed to import required modules after installing dependencies: {e}")
        print("Please ensure all dependencies are installed correctly.")
        sys.exit(1)
    
    _handle_cli_args()
    main_menu()
