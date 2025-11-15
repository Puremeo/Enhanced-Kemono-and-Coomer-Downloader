import os
import sys
import json
from typing import Literal, Dict, Optional
from dataclasses import dataclass

# Singleton cache for domains
DOMAINS: Optional[Dict[str, str]] = None


@dataclass
class Config:
    """Configuration class with type hints for all config fields"""

    get_empty_posts: bool = False
    process_from_oldest: bool = False
    post_info: Literal["md", "txt"] = "md"
    save_info: bool = False
    save_preview: bool = False
    skip_existed_files: bool = True
    post_folder_name: Literal["id", "title"] = "id"
    # Authentication for API (optional)
    coomer_api_token: Optional[str] = None
    coomer_cookie: Optional[str] = None
    # Saved login credentials (stored if user chooses to save them)
    coomer_username: Optional[str] = None
    coomer_password: Optional[str] = None
    # Favorites API options
    favorites_endpoint: Optional[str] = None  # override default endpoint
    favorites_limit: Optional[int] = None  # max number of favorite accounts to fetch
    favorites_page_size: int = 50
    favorites_rate_limit_seconds: float = 0.5
    # Performance optimization options
    favorites_extract_workers: int = 3  # number of concurrent workers for extracting posts
    favorites_download_workers: int = 2  # number of concurrent workers for downloading posts
    download_max_workers: int = 5  # number of concurrent file downloads per post
    post_download_delay_seconds: float = 0.5  # delay between posts during download
    file_verify_workers: int = 10  # number of concurrent workers for verifying file sizes
    strict_file_verification: bool = False  # if True, always verify remote size even for existing files
    use_parallel_extract_download: bool = True  # if True, download posts while extracting (faster)
    parallel_download_workers: int = 3  # number of concurrent workers for downloading posts in parallel mode
    use_concurrent_post_processing: bool = True  # if True, process multiple post links concurrently
    concurrent_post_workers: int = 3  # number of concurrent workers for processing multiple post links

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config instance from dictionary with validation"""
        return cls(
            get_empty_posts=data.get("get_empty_posts", False),
            process_from_oldest=data.get("process_from_oldest", False),
            post_info=data.get("post_info", "md"),
            save_info=data.get("save_info", False),
            save_preview=data.get("save_preview", False),
            skip_existed_files=data.get("skip_existed_files", True),
            post_folder_name=data.get("post_folder_name", "id"),
            coomer_api_token=data.get("coomer_api_token"),
            coomer_cookie=data.get("coomer_cookie"),
            coomer_username=data.get("coomer_username"),
            coomer_password=data.get("coomer_password"),
            favorites_endpoint=data.get("favorites_endpoint"),
            favorites_limit=data.get("favorites_limit"),
            favorites_page_size=data.get("favorites_page_size", 50),
            favorites_rate_limit_seconds=data.get("favorites_rate_limit_seconds", 0.5),
            favorites_extract_workers=data.get("favorites_extract_workers", 3),
            favorites_download_workers=data.get("favorites_download_workers", 2),
            download_max_workers=data.get("download_max_workers", 5),
            post_download_delay_seconds=data.get("post_download_delay_seconds", 0.5),
            file_verify_workers=data.get("file_verify_workers", 10),
            strict_file_verification=data.get("strict_file_verification", False),
            use_parallel_extract_download=data.get("use_parallel_extract_download", True),
            parallel_download_workers=data.get("parallel_download_workers", 3),
            use_concurrent_post_processing=data.get("use_concurrent_post_processing", True),
            concurrent_post_workers=data.get("concurrent_post_workers", 3),
        )
    def to_dict(self) -> dict:
        """Convert Config instance to dictionary for JSON serialization"""
        return {
            "get_empty_posts": self.get_empty_posts,
            "process_from_oldest": self.process_from_oldest,
            "post_info": self.post_info,
            "save_info": self.save_info,
            "save_preview": self.save_preview,
            "skip_existed_files": self.skip_existed_files,
            "post_folder_name": self.post_folder_name,
            "coomer_api_token": self.coomer_api_token,
            "coomer_cookie": self.coomer_cookie,
            "coomer_username": self.coomer_username,
            "coomer_password": self.coomer_password,
            "favorites_endpoint": self.favorites_endpoint,
            "favorites_limit": self.favorites_limit,
            "favorites_page_size": self.favorites_page_size,
            "favorites_rate_limit_seconds": self.favorites_rate_limit_seconds,
            "favorites_extract_workers": self.favorites_extract_workers,
            "favorites_download_workers": self.favorites_download_workers,
            "download_max_workers": self.download_max_workers,
            "post_download_delay_seconds": self.post_download_delay_seconds,
            "file_verify_workers": self.file_verify_workers,
            "strict_file_verification": self.strict_file_verification,
            "use_parallel_extract_download": self.use_parallel_extract_download,
            "parallel_download_workers": self.parallel_download_workers,
            "use_concurrent_post_processing": self.use_concurrent_post_processing,
            "concurrent_post_workers": self.concurrent_post_workers,
        }



def load_config(config_path: str = "config/conf.json") -> Config:
    """
    Load configurations from conf.json file
    If the file doesn't exist, return default configurations
    """
    try:
        with open(config_path, "r") as file:
            config_data = json.load(file)
        return Config.from_dict(config_data)
    except FileNotFoundError:
        print(f"Config file {config_path} not found. Using default settings.")
        return Config()
    except json.JSONDecodeError:
        print(f"Error decoding {config_path}. Using default settings.")
        return Config()


def save_config(config: Config, config_path: str = "config/conf.json") -> None:
    """
    Save Config instance to JSON file
    """
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as file:
            json.dump(config.to_dict(), file, indent=4)
    except Exception as e:
        print(f"Error saving config to {config_path}: {e}")


def get_domains() -> Dict[str, str]:
    """
    Get the current domain mappings for Kemono and Coomer from domain.json file.
    Uses singleton pattern to cache the result and avoid repeated file I/O.
    Returns a dictionary with service names as keys and domains as values.

    To update domains, edit config/domain.json and restart the application.

    If any error occurs, the process will terminate.
    """
    global DOMAINS

    if DOMAINS is not None:
        return DOMAINS

    domain_file_path = os.path.join("config", "domain.json")

    try:
        with open(domain_file_path, "r", encoding="utf-8") as file:
            domains = json.load(file)

        # Validate that we have the required domains
        if "kemono" not in domains:
            print(f"CRITICAL ERROR: 'kemono' key not found in {domain_file_path}")
            print("domain.json must contain both 'kemono' and 'coomer' keys")
            sys.exit(1)

        if "coomer" not in domains:
            print(f"CRITICAL ERROR: 'coomer' key not found in {domain_file_path}")
            print("domain.json must contain both 'kemono' and 'coomer' keys")
            sys.exit(1)

        DOMAINS = domains
        return domains

    except FileNotFoundError:
        print(f"CRITICAL ERROR: Configuration file {domain_file_path} not found!")
        print("Please ensure config/domain.json exists with the following format:")
        print("{")
        print('    "kemono": "kemono.cr",')
        print('    "coomer": "coomer.su"')
        print("}")
        sys.exit(1)

    except json.JSONDecodeError as e:
        print(f"CRITICAL ERROR: Failed to parse {domain_file_path}")
        print(f"JSON Error: {e}")
        print("Please ensure domain.json contains valid JSON format:")
        print("{")
        print('    "kemono": "kemono.cr",')
        print('    "coomer": "coomer.su"')
        print("}")
        sys.exit(1)

    except Exception as e:
        print(f"CRITICAL ERROR: Unexpected error reading {domain_file_path}")
        print(f"Error: {e}")
        sys.exit(1)


def reload_domains() -> Dict[str, str]:
    """
    Force reload of domain configuration from file.
    Useful if domain.json has been updated during runtime.
    """
    global DOMAINS
    DOMAINS = None
    return get_domains()
