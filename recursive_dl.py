#!/usr/bin/env python
"""
Simple Recursive Downloader
Downloads files by recursively following links based on search patterns.
"""

import argparse
import os
import requests
import time
import sys
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

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
browser_pool = Queue()
browser_type = "chrome"
verbose_mode = False
browser_lock = threading.Lock()


def create_browser(browser_name="chrome"):
    """Create a new browser instance"""
    if not SELENIUM_AVAILABLE:
        print("Error: Selenium not available. Install with: pip install selenium")
        sys.exit(1)

    try:
        if browser_name == "chrome":
            options = ChromeOptions()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
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
        print(f"Error creating {browser_name} browser: {e}")
        return None


def get_browser():
    """Get a browser from the pool or create a new one"""
    try:
        return browser_pool.get_nowait()
    except:
        return create_browser(browser_type)


def return_browser(driver):
    """Return a browser to the pool"""
    if driver:
        browser_pool.put(driver)


def cleanup_all_browsers():
    """Clean up all browsers in the pool"""
    while not browser_pool.empty():
        try:
            driver = browser_pool.get_nowait()
            driver.quit()
        except:
            break


def get_page(url, mode="requests", referer=None, driver=None):
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
            if not driver:
                driver = get_browser()
                should_return = True
            else:
                should_return = False

            if not driver:
                return None

            try:
                driver.get(url)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(1)  # Reduced wait time
                soup = BeautifulSoup(driver.page_source, "html.parser")

                if should_return:
                    return_browser(driver)

                return soup
            except Exception as e:
                if verbose_mode:
                    print(f"Error with browser for {url}: {e}")
                if should_return and driver:
                    return_browser(driver)
                return None

    except Exception as e:
        if verbose_mode:
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
    if len(unique_links) > 0 and verbose_mode:
        print(f"    Found {len(unique_links)} unique {pattern} links")
    return unique_links


def download_file(url, output_dir, mode="requests"):
    """Download a file"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        # Get proper filename from headers
        if verbose_mode:
            print(f"Getting file info for: {os.path.basename(urlparse(url).path)}")

        head_response = session.head(
            url, headers=headers, timeout=30, allow_redirects=True
        )

        # Try to get filename from Content-Disposition header
        filename = None
        if "content-disposition" in head_response.headers:
            content_disposition = head_response.headers["content-disposition"]
            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[1].strip("\"'")

        # Fallback to URL basename if no header filename
        if not filename:
            filename = os.path.basename(urlparse(url).path)
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
            print(f"✓ {filename}")
            return True

        print(f"⬇ {filename}")

        # Download the file
        response = session.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        return True

    except Exception as e:
        print(f"✗ Failed: {os.path.basename(url)} - {e}")
        return False


def process_link_worker(args):
    """Worker function for processing a single link with its own browser"""
    (
        link,
        remaining_patterns,
        depth,
        mode,
        output_dir,
        delay,
        link_index,
        total_links,
    ) = args

    # Get a browser for this worker
    driver = get_browser() if mode in ["chrome", "firefox"] else None

    try:
        if verbose_mode:
            clean_name = os.path.basename(link)
            from urllib.parse import unquote

            clean_name = unquote(clean_name)
            print(f"  [{link_index}/{total_links}] Worker processing: {clean_name}")

        count = recursive_search_single(
            link, remaining_patterns, depth + 1, mode, output_dir, delay, driver
        )
        return count

    finally:
        # Return browser to pool
        if driver and mode in ["chrome", "firefox"]:
            return_browser(driver)


def recursive_search_single(
    url,
    patterns,
    depth=0,
    mode="requests",
    output_dir="downloads",
    delay=1.0,
    driver=None,
):
    """Process a single recursive search path"""
    if not patterns:
        return 0

    indent = "  " * depth
    pattern = patterns[0]
    remaining_patterns = patterns[1:]

    if verbose_mode:
        print(f"{indent}Searching {url} for {pattern}")

    # Add delay between requests
    if depth > 0:
        time.sleep(delay + random.uniform(0, 0.5))

    # Get the page
    soup = get_page(url, mode, driver=driver)
    if not soup:
        if verbose_mode:
            print(f"{indent}Failed to fetch page")
        return 0

    # Find matching links
    links = find_links(soup, url, pattern)

    if verbose_mode and len(links) > 0:
        print(f"{indent}Found {len(links)} {pattern} links")

    if not links:
        return 0

    download_count = 0

    for i, link in enumerate(links, 1):
        if remaining_patterns:
            # More patterns to process - recurse
            count = recursive_search_single(
                link, remaining_patterns, depth + 1, mode, output_dir, delay, driver
            )
            download_count += count
        else:
            # Final pattern - download the file
            if download_file(link, output_dir, mode):
                download_count += 1

        # Small delay between items
        time.sleep(0.3)

    return download_count


def recursive_search(
    url,
    patterns,
    depth=0,
    mode="requests",
    output_dir="downloads",
    delay=1.0,
    max_workers=4,
):
    """Recursively search using concurrent browsers when beneficial"""
    if not patterns:
        return 0

    indent = "  " * depth
    pattern = patterns[0]
    remaining_patterns = patterns[1:]

    if verbose_mode:
        print(f"{indent}Searching {url} for {pattern}")

    # Get the page
    soup = get_page(url, mode)
    if not soup:
        if verbose_mode:
            print(f"{indent}Failed to fetch page")
        return 0

    # Find matching links
    links = find_links(soup, url, pattern)

    # Show link count
    if not verbose_mode and len(links) > 0:
        print(f"{indent}Found {len(links)} {pattern} links")
    elif verbose_mode:
        print(f"{indent}Found {len(links)} {pattern} links")

    if not links:
        return 0

    download_count = 0

    # Decide whether to use concurrent processing
    use_concurrent = (
        len(links) > 1 and remaining_patterns and mode in ["chrome", "firefox"]
    )

    if use_concurrent:
        # Use concurrent browsers for multiple links
        if not verbose_mode:
            print(
                f"{indent}Processing {len(links)} links with {min(max_workers, len(links))} concurrent browsers..."
            )

        # Prepare worker arguments
        worker_args = [
            (
                link,
                remaining_patterns,
                depth,
                mode,
                output_dir,
                delay,
                i + 1,
                len(links),
            )
            for i, link in enumerate(links)
        ]

        # Process links concurrently
        with ThreadPoolExecutor(max_workers=min(max_workers, len(links))) as executor:
            futures = [
                executor.submit(process_link_worker, args) for args in worker_args
            ]

            for future in as_completed(futures):
                try:
                    count = future.result()
                    download_count += count
                except Exception as e:
                    if verbose_mode:
                        print(f"Worker error: {e}")
    else:
        # Process links sequentially (original behavior)
        for i, link in enumerate(links, 1):
            # Clean filename display
            clean_name = os.path.basename(link)
            from urllib.parse import unquote

            clean_name = unquote(clean_name)

            if verbose_mode:
                print(f"{indent}[{i}/{len(links)}] Processing: {clean_name}")
            elif depth == 0:  # Only show progress at top level
                print(f"[{i}/{len(links)}] {clean_name}")

            if remaining_patterns:
                # More patterns to process - recurse
                count = recursive_search(
                    link,
                    remaining_patterns,
                    depth + 1,
                    mode,
                    output_dir,
                    delay,
                    max_workers,
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
  
  # Show detailed output
  python run.py 'https://example.com' --search *.mp3 *.mp3 --verbose
  
  # Speed up with more concurrent browsers
  python run.py 'https://example.com' --search *.mp3 *.mp3 --mode chrome --workers 8
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
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=4,
        help="Max concurrent browsers for Selenium mode (default: 4)",
    )

    args = parser.parse_args()

    # Set global verbose mode and browser type
    global verbose_mode, browser_type
    verbose_mode = args.verbose
    browser_type = args.mode

    print(f"Starting recursive download from: {args.url}")
    print(f"Search patterns: {' -> '.join(args.search)}")
    print(f"Mode: {args.mode}")
    print(f"Output: {args.output}")
    if args.mode in ["chrome", "firefox"]:
        print(f"Concurrent browsers: {args.workers}")
    if verbose_mode:
        print(f"Verbose: enabled")
    print("-" * 50)

    try:
        # Start recursive search
        count = recursive_search(
            args.url,
            args.search,
            mode=args.mode,
            output_dir=args.output,
            delay=args.delay,
            max_workers=args.workers,
        )

        print(f"\n✅ Completed! Downloaded {count} files to '{args.output}'")

    except KeyboardInterrupt:
        print("\n❌ Interrupted by user")
    finally:
        # Cleanup all browsers
        cleanup_all_browsers()


if __name__ == "__main__":
    main()
