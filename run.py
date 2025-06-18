#!/usr/bin/env python3
"""
Simple Recursive Downloader
Downloads files by recursively following links based on search patterns.
"""

import argparse
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import sys
import random

# Selenium imports (optional)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Global variables
session = requests.Session()
driver = None


def setup_browser(browser_type="chrome"):
    """Setup and return selenium driver"""
    global driver

    if not SELENIUM_AVAILABLE:
        print("Error: Selenium not available. Install with: pip install selenium")
        sys.exit(1)

    try:
        if browser_type == "chrome":
            options = ChromeOptions()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            driver = webdriver.Chrome(options=options)
        else:  # firefox
            options = FirefoxOptions()
            options.set_preference("dom.webdriver.enabled", False)
            driver = webdriver.Firefox(options=options)

        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver
    except Exception as e:
        print(f"Error setting up {browser_type}: {e}")
        sys.exit(1)


def get_page(url, mode="requests", referer=None):
    """Get page content using requests or selenium"""
    try:
        if mode == "requests":
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": referer or url,
            }
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, "html.parser")
        else:
            global driver
            if not driver:
                driver = setup_browser(mode)
            driver.get(url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(2)
            return BeautifulSoup(driver.page_source, "html.parser")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


def find_links(soup, base_url, pattern):
    """Find all links matching pattern"""
    if not soup:
        return []

    extension = pattern.replace("*", "")
    links = set()  # Use set to automatically remove duplicates

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.endswith(extension):
            full_url = urljoin(base_url, href)
            links.add(full_url)

    unique_links = list(links)
    if len(unique_links) > 0:
        print(f"    Found {len(unique_links)} unique {pattern} links")
    return unique_links


def download_file(url, output_dir, mode="requests"):
    """Download a file"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        # First, make a HEAD request to get the proper filename
        print(f"Getting file info for: {os.path.basename(urlparse(url).path)}")
        head_response = session.head(
            url, headers=headers, timeout=30, allow_redirects=True
        )

        # Try to get filename from Content-Disposition header
        filename = None
        if "content-disposition" in head_response.headers:
            content_disposition = head_response.headers["content-disposition"]
            if "filename=" in content_disposition:
                # Extract filename from header like: attachment; filename="song.mp3"
                filename = content_disposition.split("filename=")[1].strip("\"'")

        # Fallback to URL basename if no header filename
        if not filename:
            filename = os.path.basename(urlparse(url).path)
            # URL decode the filename to get proper characters
            from urllib.parse import unquote

            filename = unquote(filename)

        # Clean up filename (remove invalid characters)
        import re

        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

        # Ensure we have a filename
        if not filename or filename == "/":
            filename = f"file_{int(time.time())}"

        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath):
            print(f"Exists: {filename}")
            return True

        print(f"Downloading: {filename}")

        # Now download the actual file
        response = session.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"Downloaded: {filename}")
        return True

    except Exception as e:
        print(f"Download failed {url}: {e}")
        return False


def recursive_search(
    url, patterns, depth=0, mode="requests", output_dir="downloads", delay=1.0
):
    """Recursively search and download based on patterns"""
    if not patterns:
        return 0

    indent = "  " * depth
    pattern = patterns[0]
    remaining_patterns = patterns[1:]

    print(f"{indent}Searching {url} for {pattern}")

    # Add delay between requests
    if depth > 0:
        time.sleep(delay + random.uniform(0, 1))

    # Get the page
    soup = get_page(url, mode)
    if not soup:
        print(f"{indent}Failed to fetch page")
        return 0

    # Find matching links
    links = find_links(soup, url, pattern)
    print(f"{indent}Found {len(links)} {pattern} links")

    if not links:
        return 0

    download_count = 0

    for i, link in enumerate(links, 1):
        print(f"{indent}[{i}/{len(links)}] Processing: {os.path.basename(link)}")

        if remaining_patterns:
            # More patterns to process - recurse
            count = recursive_search(
                link, remaining_patterns, depth + 1, mode, output_dir, delay
            )
            download_count += count
        else:
            # Final pattern - download the file
            if download_file(link, output_dir, mode):
                download_count += 1

        # Small delay between items
        time.sleep(0.5)

    return download_count


def main():
    parser = argparse.ArgumentParser(
        description="Recursively download files following link patterns",
        epilog="""
Examples:
  # Find .mp3 links, then download .mp3 files from each
  python run.py 'https://example.com' --search *.mp3 *.mp3
  
  # Find .html pages, then .mp3 links, then download .mp3 files  
  python run.py 'https://example.com' --search *.html *.mp3 *.mp3
  
  # Use browser mode for protected sites
  python run.py 'https://example.com' --search *.mp3 *.mp3 --mode chrome
        """,
    )

    parser.add_argument("url", help="Starting URL")
    parser.add_argument(
        "--search",
        nargs="+",
        required=True,
        help="Search patterns in order (e.g., *.html *.mp3 *.mp3)",
    )
    parser.add_argument(
        "--mode",
        choices=["requests", "chrome", "firefox"],
        default="requests",
        help="Fetching mode (default: requests)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="downloads",
        help="Output directory (default: downloads)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1.0)",
    )

    args = parser.parse_args()

    print(f"Starting recursive download from: {args.url}")
    print(f"Search patterns: {' -> '.join(args.search)}")
    print(f"Mode: {args.mode}")
    print(f"Output: {args.output}")
    print("-" * 50)

    try:
        # Start recursive search
        count = recursive_search(
            args.url,
            args.search,
            mode=args.mode,
            output_dir=args.output,
            delay=args.delay,
        )

        print(f"\nCompleted! Downloaded {count} files to '{args.output}'")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        # Cleanup
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
