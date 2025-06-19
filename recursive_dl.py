#!/usr/bin/env python
"""
Simple Recursive Downloader
Downloads files by recursively following links based on search patterns.
"""

import argparse
import os
import re
import sys
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values

# Load environment variables
env = {
    k: v
    for k, v in dotenv_values(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    ).items()
    if v.strip()
}

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
# Configure session for better concurrency and reliability
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
)
# Set connection pooling for better concurrent performance
adapter = requests.adapters.HTTPAdapter(
    pool_connections=20, pool_maxsize=20, max_retries=3
)
session.mount("http://", adapter)
session.mount("https://", adapter)

browser_pool = Queue()
verbose_mode = False


def create_browser(browser_name="chrome"):
    """Create a new browser instance"""
    if not SELENIUM_AVAILABLE:
        print("Error: Selenium not available. Install with: pip install selenium")
        sys.exit(1)

    try:
        if browser_name == "chrome":
            options = ChromeOptions()
            for arg in [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]:
                options.add_argument(arg)
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
        print(f"Error creating {browser_name} browser: {e}")
        return None


def get_browser(browser_type):
    """Get a browser from the pool or create a new one"""
    try:
        return browser_pool.get_nowait()
    except:
        return create_browser(browser_type)


def cleanup_browsers():
    """Clean up all browsers in the pool"""
    while not browser_pool.empty():
        try:
            browser_pool.get_nowait().quit()
        except:
            break


def get_page(url, mode="requests", driver=None, browser_type="chrome"):
    """Get page content using requests or selenium"""
    try:
        if mode == "requests":
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
            # Add a small random delay to avoid rate limiting
            time.sleep(random.uniform(0.5, 1.5))
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, "html.parser")
        else:
            should_return = driver is None
            if not driver:
                driver = get_browser(browser_type)
            if not driver:
                return None

            try:
                driver.get(url)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(1)
                soup = BeautifulSoup(driver.page_source, "html.parser")
                if should_return:
                    browser_pool.put(driver)
                return soup
            except Exception as e:
                if verbose_mode:
                    print(f"Error with browser for {url}: {e}")
                if should_return and driver:
                    browser_pool.put(driver)
                return None
    except Exception as e:
        if verbose_mode:
            print(f"Error fetching {url}: {e}")
        return None


def parse_pattern(pattern_str):
    """Parse a pattern string that may contain fallback patterns separated by '>'

    Examples:
        "*.mp3" -> ["*.mp3"]
        "*.flac>*.mp3" -> ["*.flac", "*.mp3"]
        "*.flac>*.ogg>*.mp3" -> ["*.flac", "*.ogg", "*.mp3"]
    """
    if ">" in pattern_str:
        return [p.strip() for p in pattern_str.split(">")]
    return [pattern_str]


def find_links_with_fallback(soup, base_url, pattern_str):
    """Find links with fallback pattern support"""
    if not soup:
        return []

    fallback_patterns = parse_pattern(pattern_str)

    for pattern in fallback_patterns:
        links = find_links(soup, base_url, pattern)
        if links:
            if verbose_mode and len(fallback_patterns) > 1:
                print(f"    Using pattern {pattern} (found {len(links)} links)")
            return links
        elif verbose_mode and len(fallback_patterns) > 1:
            print(f"    No matches for {pattern}, trying fallback...")

    return []


def find_links(soup, base_url, pattern):
    """Find all links matching pattern"""
    if not soup:
        return []

    extension = pattern.replace("*", "")
    links = {
        urljoin(base_url, link["href"])
        for link in soup.find_all("a", href=True)
        if link["href"].endswith(extension)
    }

    if links and verbose_mode:
        print(f"    Found {len(links)} unique {pattern} links")
    return list(links)


def download_file(url, output_dir):
    """Download a file"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }

        if verbose_mode:
            print(f"Getting file info for: {os.path.basename(urlparse(url).path)}")

        # Get filename from headers or URL
        head_response = session.head(
            url, headers=headers, timeout=30, allow_redirects=True
        )
        filename = None

        if "content-disposition" in head_response.headers:
            content_disposition = head_response.headers["content-disposition"]
            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[1].strip("\"'")

        if not filename:
            filename = unquote(os.path.basename(urlparse(url).path))

        # Clean filename and ensure it's valid
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename) or f"file_{int(time.time())}"

        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath):
            print(f"✓ {filename}")
            return True

        print(f"⬇ {filename}")
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


def process_worker(args):
    """Worker function for concurrent processing"""
    (
        link,
        patterns,
        depth,
        mode,
        output_dir,
        delay,
        link_index,
        total_links,
        browser_type,
    ) = args

    driver = get_browser(browser_type) if mode in ["chrome", "firefox"] else None
    try:
        if verbose_mode:
            clean_name = unquote(os.path.basename(link))
            print(f"  [{link_index}/{total_links}] Worker processing: {clean_name}")

        count = recursive_search(
            link, patterns, depth + 1, mode, output_dir, delay, 1, browser_type, driver
        )
        return count
    finally:
        if driver and mode in ["chrome", "firefox"]:
            browser_pool.put(driver)


def recursive_search(
    url,
    patterns,
    depth=0,
    mode="requests",
    output_dir="downloads",
    delay=1.0,
    max_workers=4,
    browser_type="chrome",
    driver=None,
):
    """Recursively search and download files"""
    if not patterns:
        return 0

    indent = "  " * depth
    pattern = patterns[0]
    remaining_patterns = patterns[1:]

    if verbose_mode:
        print(f"{indent}Searching {url} for {pattern}")

    # Add delay for non-root requests
    if depth > 0:
        time.sleep(delay + random.uniform(0, 0.5))

    soup = get_page(url, mode, driver, browser_type)
    if not soup:
        if verbose_mode:
            print(f"{indent}Failed to fetch page")
        return 0

    links = find_links_with_fallback(soup, url, pattern)

    if not verbose_mode and links:
        # Show which pattern was actually used for fallback patterns
        if ">" in pattern:
            fallback_patterns = parse_pattern(pattern)
            used_pattern = None
            # Find which pattern was actually used by checking what links we found
            for p in fallback_patterns:
                test_links = find_links(soup, url, p)
                if test_links:
                    used_pattern = p
                    break
            if used_pattern and used_pattern != fallback_patterns[0]:
                print(
                    f"{indent}Found {len(links)} {used_pattern} links (fallback from {fallback_patterns[0]})"
                )
            else:
                print(f"{indent}Found {len(links)} {pattern} links")
        else:
            print(f"{indent}Found {len(links)} {pattern} links")
    elif verbose_mode and links:
        print(f"{indent}Found {len(links)} links for pattern {pattern}")

    if not links:
        return 0

    download_count = 0

    # Use concurrent processing for multiple links with remaining patterns
    use_concurrent = len(links) > 1 and remaining_patterns and depth == 0

    if use_concurrent:
        worker_type = "workers" if mode == "requests" else "concurrent browsers"
        if not verbose_mode:
            print(
                f"{indent}Processing {len(links)} links with {min(max_workers, len(links))} {worker_type}..."
            )

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
                browser_type,
            )
            for i, link in enumerate(links)
        ]

        with ThreadPoolExecutor(max_workers=min(max_workers, len(links))) as executor:
            futures = [executor.submit(process_worker, args) for args in worker_args]
            for future in as_completed(futures):
                try:
                    download_count += future.result()
                except Exception as e:
                    if verbose_mode:
                        print(f"Worker error: {e}")
    else:
        # Check if we should use concurrent downloading for final files
        use_concurrent_download = (
            len(links) > 1 and not remaining_patterns and depth == 0 and max_workers > 1
        )

        if use_concurrent_download:
            worker_type = "download workers"
            if not verbose_mode:
                print(
                    f"{indent}Downloading {len(links)} files with {min(max_workers, len(links))} {worker_type}..."
                )

            download_args = [(link, output_dir) for link in links]

            with ThreadPoolExecutor(
                max_workers=min(max_workers, len(links))
            ) as executor:
                futures = [
                    executor.submit(download_file, *args) for args in download_args
                ]
                for future in as_completed(futures):
                    try:
                        if future.result():
                            download_count += 1
                    except Exception as e:
                        if verbose_mode:
                            print(f"Download error: {e}")
        else:
            # Sequential processing
            for i, link in enumerate(links, 1):
                clean_name = unquote(os.path.basename(link))

                if verbose_mode:
                    print(f"{indent}[{i}/{len(links)}] Processing: {clean_name}")
                elif depth == 0:
                    print(f"[{i}/{len(links)}] {clean_name}")

                if remaining_patterns:
                    download_count += recursive_search(
                        link,
                        remaining_patterns,
                        depth + 1,
                        mode,
                        output_dir,
                        delay,
                        max_workers,
                        browser_type,
                        driver,
                    )
                else:
                    if download_file(link, output_dir):
                        download_count += 1

                time.sleep(0.3 if remaining_patterns else 0.5)

    return download_count


def main():
    parser = argparse.ArgumentParser(
        description="Recursively download files following link patterns",
        epilog="""
Examples:
  # Find .mp3 links, then download .mp3 files from each
  python recursive_dl.py 'https://example.com' --search *.mp3 *.mp3
  
  # Find .html pages, then .mp3 links, then download .mp3 files  
  python recursive_dl.py 'https://example.com' --search *.html *.mp3 *.mp3
  
  # Try .flac first, fallback to .mp3 if no .flac files found
  python recursive_dl.py 'https://example.com' --search *.mp3 '*.flac>*.mp3'
  
  # Multiple fallbacks: try .flac, then .ogg, then .mp3
  python recursive_dl.py 'https://example.com' --search *.mp3 '*.flac>*.ogg>*.mp3'
  
  # Use browser mode for protected sites
  python recursive_dl.py 'https://example.com' --search *.mp3 *.mp3 --mode chrome
        """,
    )

    parser.add_argument("url", help="Starting URL")
    parser.add_argument(
        "--search",
        nargs="+",
        default=env.get("SEARCH", "").split() or [],
        help="Search patterns in order (e.g., *.html *.mp3 *.mp3). Supports fallbacks with '>' (e.g., '*.flac>*.mp3')",
    )
    parser.add_argument(
        "--mode",
        choices=["requests", "chrome", "firefox"],
        default=env.get("MODE", "requests"),
        help="Fetching mode (default: requests)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=env.get("OUTPUT", "downloads"),
        help="Output directory (default: downloads)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=float(env.get("DELAY", 1.0)),
        help="Delay between requests in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=env.get("VERBOSE", "false").lower() == "true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=int(env.get("WORKERS", 4)),
        help="Max concurrent workers/browsers (default: 4)",
    )

    args = parser.parse_args()

    if not args.search:
        raise ValueError("--search argument is required")

    global verbose_mode
    verbose_mode = args.verbose

    print(f"Starting recursive download from: {args.url}")
    print(f"Search patterns: {' -> '.join(args.search)}")
    print(f"Mode: {args.mode}")
    print(f"Output: {args.output}")
    if args.workers > 1:
        worker_type = "browsers" if args.mode in ["chrome", "firefox"] else "workers"
        print(f"Concurrent {worker_type}: {args.workers}")
    if verbose_mode:
        print("Verbose: enabled")
    print("-" * 50)

    try:
        count = recursive_search(
            args.url,
            args.search,
            mode=args.mode,
            output_dir=args.output,
            delay=args.delay,
            max_workers=args.workers,
            browser_type=args.mode,
        )
        print(f"\n✅ Completed! Downloaded {count} files to '{args.output}'")
    except KeyboardInterrupt:
        print("\n❌ Interrupted by user")
    finally:
        cleanup_browsers()


if __name__ == "__main__":
    main()
