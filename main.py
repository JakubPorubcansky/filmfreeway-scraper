#!/usr/bin/env python3
"""
FilmFreeway Festival Scraper
Scrapes festival information from FilmFreeway.com
Compliant with robots.txt (Crawl-delay: 20)
"""

import time
import argparse
from tqdm import tqdm
from typing import Optional, Dict, List, Set
import requests
from bs4 import BeautifulSoup
import logging
import random
import json
import glob
import os
from pathlib import Path
from datetime import datetime

DELAY_BETWEEN_FESTIVALS = 20
REQUEST_TIMEOUT = 30

# Rotate between multiple realistic user agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
]


class ChunkedJSONLWriter:
    """Manages writing to chunked JSONL files with automatic rotation at 10,000 entries."""

    def __init__(self, base_dir: str = "scraped", chunk_size: int = 10000):
        self.base_dir = base_dir
        self.chunk_size = chunk_size
        self.current_chunk_num = self._find_last_chunk_number()
        self.current_entry_count = self._count_entries_in_current_chunk()
        self.file_handle = None
        self._open_current_chunk()

    def _find_last_chunk_number(self) -> int:
        """Find the highest chunk number from existing files."""
        pattern = os.path.join(self.base_dir, "festivals_data_*.jsonl")
        files = glob.glob(pattern)

        if not files:
            return 1  # Start with festivals_data_1.jsonl

        # Extract numbers from filenames
        numbers = []
        for f in files:
            basename = os.path.basename(f)
            # Extract number from festivals_data_N.jsonl
            if basename.startswith("festivals_data_") and basename.endswith(".jsonl"):
                num_str = basename[len("festivals_data_"):-len(".jsonl")]
                try:
                    numbers.append(int(num_str))
                except ValueError:
                    continue

        return max(numbers) if numbers else 1

    def _count_entries_in_current_chunk(self) -> int:
        """Count entries in the current chunk file."""
        filepath = os.path.join(self.base_dir, f"festivals_data_{self.current_chunk_num}.jsonl")

        if not os.path.exists(filepath):
            return 0

        count = 0
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    count += 1

        return count

    def _open_current_chunk(self, log_message: bool = True):
        """Open the current chunk file in append mode."""
        filepath = os.path.join(self.base_dir, f"festivals_data_{self.current_chunk_num}.jsonl")
        self.file_handle = open(filepath, 'a', encoding='utf-8')
        if log_message:
            logging.info(f"Writing to {filepath} (current entries: {self.current_entry_count})")

    def write(self, festival_data: Dict):
        """Write festival data, rotating to new file if current reaches chunk_size."""
        # Check if we need to rotate to a new file
        if self.current_entry_count >= self.chunk_size:
            self.file_handle.close()
            self.current_chunk_num += 1
            self.current_entry_count = 0
            # Don't log during rotation to avoid interrupting progress bar
            self._open_current_chunk(log_message=False)

        # Write the data
        json.dump(festival_data, self.file_handle, ensure_ascii=False)
        self.file_handle.write('\n')
        self.file_handle.flush()  # Ensure data is written
        self.current_entry_count += 1

    def close(self):
        """Close the current file handle."""
        if self.file_handle:
            filepath = os.path.join(self.base_dir, f"festivals_data_{self.current_chunk_num}.jsonl")
            self.file_handle.close()
            logging.info(f"Closed {filepath} with {self.current_entry_count} entries")


# Global writer instance
chunked_writer = None


def save_festival(festival_data: Dict, output_file: str = "festivals_data.jsonl"):
    """Save festival data using chunked writer."""
    global chunked_writer
    if chunked_writer is None:
        chunked_writer = ChunkedJSONLWriter(base_dir="scraped", chunk_size=10000)
    chunked_writer.write(festival_data)


def get_session() -> requests.Session:
    """Create a session with proper headers mimicking a real browser."""
    session = requests.Session()

    # Set comprehensive browser-like headers
    session.headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'TE': 'trailers',
    })

    return session


def fetch_sitemap_urls(sitemap_url: str = "https://filmfreeway.com/pages/sitemap_for_festivals", retry_count: int = 3) -> List[str]:
    """Fetch sitemap and return list of festival URLs with retry logic."""
    session = get_session()

    for attempt in range(retry_count):
        try:
            # Rotate user agent for each attempt
            session.headers['User-Agent'] = random.choice(USER_AGENTS)
            session.headers['Referer'] = 'https://filmfreeway.com/'

            logging.info(f"Fetching sitemap from {sitemap_url}...")
            response = session.get(sitemap_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            response.raise_for_status()

            # Parse as plain text file (one URL per line)
            urls = [line.strip() for line in response.text.splitlines() if line.strip()]

            logging.info(f"Successfully fetched {len(urls)} URLs from sitemap")
            return urls

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code

            if status_code == 403:
                if attempt < retry_count - 1:
                    wait_time = 15 * (2 ** attempt)
                    logging.warning(
                        f"403 Forbidden for sitemap (attempt {attempt + 1}/{retry_count}). "
                        f"Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logging.error(f"Failed to fetch sitemap after {retry_count} attempts: 403 Forbidden")
                    raise
            else:
                logging.error(f"HTTP {status_code} error for sitemap")
                raise

        except requests.exceptions.Timeout:
            if attempt < retry_count - 1:
                logging.warning(f"Timeout on attempt {attempt + 1}/{retry_count} for sitemap. Retrying...")
                time.sleep(5)
                continue
            else:
                logging.error(f"Timeout after {retry_count} attempts for sitemap")
                raise

        except requests.exceptions.RequestException as e:
            if attempt < retry_count - 1:
                logging.warning(f"Request error on attempt {attempt + 1}/{retry_count}: {str(e)}. Retrying...")
                time.sleep(5)
                continue
            else:
                logging.error(f"Request failed after {retry_count} attempts: {str(e)}")
                raise

        except Exception as e:
            logging.error(f"Unexpected error fetching sitemap: {str(e)}")
            raise

    return []


def load_scraped_urls(scraped_dir: str = "scraped") -> Set[str]:
    """Load all previously scraped URLs from all festivals_data_*.jsonl files."""
    scraped_urls = set()

    # Find all matching files
    pattern = os.path.join(scraped_dir, "festivals_data_*.jsonl")
    files = glob.glob(pattern)

    if not files:
        logging.info("No existing scraped files found, starting fresh")
        return scraped_urls

    # Read each file
    for filepath in sorted(files):  # Sort for consistent logging
        file_count = 0
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if line.strip():
                        try:
                            record = json.loads(line)
                            if 'url' in record:
                                scraped_urls.add(record['url'].strip())
                                file_count += 1
                        except json.JSONDecodeError as e:
                            logging.warning(f"Skipping malformed JSON in {filepath} at line {line_num}: {str(e)}")
                            continue

            logging.info(f"Loaded {file_count} URLs from {os.path.basename(filepath)}")
        except Exception as e:
            logging.error(f"Error reading {filepath}: {str(e)}")

    return scraped_urls


def confirm_scraping(new_count: int, total_sitemap: int, scraped_count: int, count_arg: Optional[str] = None) -> tuple[bool, Optional[int]]:
    """Display stats and ask user for confirmation and count.

    Returns:
        tuple: (should_scrape: bool, count_to_scrape: Optional[int])
               count_to_scrape is None if 'all' is selected
    """
    print("\n" + "=" * 80)
    print("SCRAPING SUMMARY")
    print("=" * 80)
    print(f"Total festivals in sitemap:  {total_sitemap:,}")
    print(f"Already scraped:             {scraped_count:,}")
    print(f"New festivals available:     {new_count:,}")
    print("=" * 80 + "\n")

    try:
        # Ask for confirmation
        response = input("Do you want to start scraping? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            return False, None

        # Determine count to scrape
        scrape_count = None
        if count_arg is not None:
            # Count provided via command line
            if count_arg.lower() == 'all':
                scrape_count = None  # None means all
                print(f"Scraping all {new_count:,} new festivals")
            else:
                try:
                    scrape_count = int(count_arg)
                    if scrape_count <= 0:
                        print("Error: Count must be positive")
                        return False, None
                    scrape_count = min(scrape_count, new_count)  # Cap at available
                    print(f"Scraping {scrape_count:,} new festivals")
                except ValueError:
                    print(f"Error: Invalid count '{count_arg}'. Must be a number or 'all'")
                    return False, None
        else:
            # Ask user for count
            count_input = input(f"How many festivals to scrape? (1-{new_count:,} or 'all'): ").strip().lower()
            if count_input == 'all':
                scrape_count = None  # None means all
            else:
                try:
                    scrape_count = int(count_input)
                    if scrape_count <= 0:
                        print("Error: Count must be positive")
                        return False, None
                    scrape_count = min(scrape_count, new_count)  # Cap at available
                except ValueError:
                    print(f"Error: Invalid input '{count_input}'. Must be a number or 'all'")
                    return False, None

        # Display estimated time
        actual_count = scrape_count if scrape_count is not None else new_count
        estimated_seconds = actual_count * DELAY_BETWEEN_FESTIVALS
        estimated_hours = estimated_seconds / 3600

        if estimated_hours < 1:
            estimated_minutes = estimated_seconds / 60
            print(f"Estimated time: ~{estimated_minutes:.1f} minutes")
        else:
            print(f"Estimated time: ~{estimated_hours:.1f} hours")
        print()

        return True, scrape_count

    except (KeyboardInterrupt, EOFError):
        print("\n")
        return False, None


def extract_section_info(section) -> Dict[str, str]:
    """
    Extract title and content from a festival information section.
    
    Args:
        section: BeautifulSoup section element
        
    Returns:
        Dict with 'title' and 'content' keys
    """
    section_data = {
        'title': '',
        'content': ''
    }
    
    # Find the section title - typically in a heading or Navigation-tab
    title_element = section.find('div', class_='Navigation-tab')
    if title_element:
        tab_span = title_element.find('span', class_='tab')
        if tab_span:
            section_data['title'] = tab_span.get_text(strip=True)
    
    # If no title found via Navigation-tab, try role="heading"
    if not section_data['title']:
        heading = section.find(attrs={'role': 'heading'})
        if heading:
            section_data['title'] = heading.get_text(strip=True)
    
    # Extract content from the section__content div
    content_div = section.find('div', class_='festival-information__section__content')
    if content_div:
        # Get all text, preserving line breaks
        section_data['content'] = content_div.get_text(separator='\n', strip=True)
    
    return section_data


def extract_dates_deadlines(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """
    Extract dates and deadlines information from the festival page.
    
    Args:
        soup: BeautifulSoup object of the festival page
        
    Returns:
        List of dictionaries containing date, deadline type, and status
    """
    dates_deadlines = []
    
    # Find the dates & deadlines section
    dates_section = soup.find('ul', class_='ProfileFestival-datesDeadlines')
    
    if not dates_section:
        return dates_deadlines
    
    # Find all date groups
    date_groups = dates_section.find_all('li', class_='ProfileFestival-datesDeadlines-dateGroup')
    
    for date_group in date_groups:
        date_info = {}
        
        # Determine status from class
        classes = date_group.get('class', [])
        if 'is-outdated' in classes:
            date_info['status'] = 'outdated'
        elif 'is-current' in classes:
            date_info['status'] = 'current'
        elif 'is-upcoming' in classes:
            date_info['status'] = 'upcoming'
        else:
            date_info['status'] = 'unknown'
        
        # Extract the time element
        time_element = date_group.find('time', class_='ProfileFestival-datesDeadlines-time')
        if time_element:
            # Get ISO datetime from datetime attribute
            date_info['datetime'] = time_element.get('datetime', '')
            # Get human-readable date
            date_info['date'] = time_element.get_text(strip=True)
        
        # Extract deadline type
        deadline_element = date_group.find('div', class_='ProfileFestival-datesDeadlines-deadline')
        if deadline_element:
            date_info['deadline_type'] = deadline_element.get_text(strip=True)
        
        # Only add if we have meaningful data
        if date_info.get('date') or date_info.get('deadline_type'):
            dates_deadlines.append(date_info)
    
    return dates_deadlines


def scrape(url: str, session: requests.Session, retry_count: int = 3) -> Dict[str, any]:
    """Scrape a single festival page with retry logic and exponential backoff."""
    url = url.strip()
    
    # Validate URL format
    if not url.startswith('https://filmfreeway.com/'):
        raise ValueError(f"Invalid FilmFreeway URL: {url}")
    
    for attempt in range(retry_count):
        try:
            # Rotate user agent for each attempt
            session.headers['User-Agent'] = random.choice(USER_AGENTS)
            
            # Set referer to look like navigation from main site
            session.headers['Referer'] = 'https://filmfreeway.com/'
            
            # Make the request
            response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            
            # Check for successful response
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the festival name in the h3 element
            festival_name_element = soup.find('h3', class_='festival-name')
            
            title = ""
            if festival_name_element:
                # Get the title from the anchor tag inside the h3
                anchor = festival_name_element.find('a')
                if anchor and anchor.get('title'):
                    title = anchor.get('title').strip()
            
            # Find the 'about' div containing festival information sections
            about_div = soup.find('div', id='about', class_='festival-information')
            
            sections = []
            if about_div:
                # Find all section elements, excluding reviews
                all_sections = about_div.find_all('section', class_='festival-information__section')
                
                for section in all_sections:
                    # Skip the reviews section
                    if 'festival-information__section--reviews' in section.get('class', []):
                        continue
                    
                    section_data = extract_section_info(section)
                    
                    # Only add sections that have content
                    if section_data['title'] or section_data['content']:
                        sections.append(section_data)
            else:
                logging.warning(f"No 'about' div found for {url}")
            
            # Extract dates and deadlines
            dates_deadlines = extract_dates_deadlines(soup)
            
            return {
                'url': url,
                'title': title,
                'sections': sections,
                'dates_deadlines': dates_deadlines
            }
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            
            if status_code == 403:
                if attempt < retry_count - 1:
                    # Exponential backoff: 15s, 30s, 60s
                    wait_time = 15 * (2 ** attempt)
                    logging.warning(
                        f"403 Forbidden for {url} (attempt {attempt + 1}/{retry_count}). "
                        f"Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logging.error(f"Failed after {retry_count} attempts: 403 Forbidden for {url}")
                    raise
            elif status_code == 404:
                logging.error(f"Festival not found (404): {url}")
                raise
            elif status_code == 429:
                # Rate limited
                wait_time = 60
                logging.warning(f"Rate limited (429). Waiting {wait_time}s...")
                time.sleep(wait_time)
                if attempt < retry_count - 1:
                    continue
                else:
                    raise
            else:
                logging.error(f"HTTP {status_code} error for {url}")
                raise
                
        except requests.exceptions.Timeout:
            if attempt < retry_count - 1:
                logging.warning(f"Timeout on attempt {attempt + 1}/{retry_count} for {url}. Retrying...")
                time.sleep(5)
                continue
            else:
                logging.error(f"Timeout after {retry_count} attempts for {url}")
                raise
                
        except requests.exceptions.RequestException as e:
            if attempt < retry_count - 1:
                logging.warning(f"Request error on attempt {attempt + 1}/{retry_count}: {str(e)}. Retrying...")
                time.sleep(5)
                continue
            else:
                logging.error(f"Request failed after {retry_count} attempts: {str(e)}")
                raise
                
        except Exception as e:
            # Parsing or other errors
            logging.error(f"Unexpected error for {url}: {str(e)}")
            raise


def scrape_festival_details(
    urls: List[str],
    count: Optional[int] = None
) -> List[Dict[str, any]]:
    """Scrape detailed information for each festival.

    Args:
        urls: List of festival URLs to scrape
        count: Number of festivals to scrape (None means all)
    """
    # Determine how many to scrape
    scrape_count = len(urls) if count is None else min(count, len(urls))

    if scrape_count <= 0:
        logging.error("No festivals to scrape")
        return []

    logging.info(f"Starting to scrape details for {scrape_count} festivals...")

    festivals_data = []
    session = get_session()
    
    # Establish session by visiting main page first
    try:
        logging.info("Establishing session with FilmFreeway...")
        session.get('https://filmfreeway.com/', timeout=REQUEST_TIMEOUT)
        logging.info("Session established successfully")
        time.sleep(3)  # Brief pause after initial connection
    except Exception as e:
        logging.warning(f"Could not establish initial session: {str(e)}")

    # Initialize chunked writer before progress bar to avoid interrupting it
    global chunked_writer
    if chunked_writer is None:
        chunked_writer = ChunkedJSONLWriter(base_dir="scraped", chunk_size=10000)

    with tqdm(total=scrape_count, desc="Scraping festival details") as pbar:
        for idx, url in enumerate(urls[:scrape_count]):
            try:
                festival_data = {}
                festival_data.update(scrape(url, session))

                # Add timestamp
                festival_data['scraped_at'] = datetime.utcnow().isoformat() + 'Z'

                festivals_data.append(festival_data)

                save_festival(festival_data)

                section_count = len(festival_data.get('sections', []))
                pbar.write(
                    f"[{idx+1}/{scrape_count}] Successfully scraped: {festival_data['title']} "
                    f"({section_count} sections)"
                )

                pbar.update(1)

                delay_variation = random.uniform(-3, 3)
                actual_delay = max(DELAY_BETWEEN_FESTIVALS + delay_variation, 0)

                if idx < scrape_count - 1:  # Don't delay after last item
                    time.sleep(actual_delay)

            except Exception as e:
                pbar.write(f"ERROR: [{idx+1}/{scrape_count}] Error processing {url.strip()}: {str(e)}")
                save_festival({"url": url})
                pbar.update(1)
                # Continue with next festival
                continue

    # Close the chunked writer
    if chunked_writer:
        chunked_writer.close()
        chunked_writer = None  # Reset for next run

    logging.info(f"Successfully scraped {len(festivals_data)} out of {scrape_count} festivals")
    return festivals_data


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    parser = argparse.ArgumentParser(
        description='Scrape festival information from FilmFreeway (robots.txt compliant)'
    )
    parser.add_argument(
        '--count', '-c',
        type=str,
        default=None,
        help='Number of new festivals to scrape (or "all" to scrape all new festivals)'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt and start scraping'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    logging.info("=" * 80)
    logging.info("FilmFreeway Festival Scraper Started")
    logging.info("Compliant with robots.txt (Crawl-delay: 20 seconds)")
    logging.info("=" * 80)

    try:
        # Fetch sitemap URLs or use input file
        try:
            sitemap_urls = fetch_sitemap_urls()
            logging.info(f"Found {len(sitemap_urls)} festivals in sitemap")
        except Exception as e:
            logging.error(f"Failed to fetch festivals sitemap: {str(e)}")
            return 

        # Load already-scraped URLs
        logging.info("Checking already scraped festivals...")
        scraped_urls = load_scraped_urls()
        logging.info(f"Found {len(scraped_urls)} already scraped festivals")

        # Find new festivals
        new_festivals = [url for url in sitemap_urls if url not in scraped_urls]
        logging.info(f"Found {len(new_festivals)} new festivals to scrape")

        # Handle count and confirmation
        if new_festivals:
            scrape_count = None

            if not args.yes:
                # Ask for confirmation and count
                should_scrape, scrape_count = confirm_scraping(
                    len(new_festivals),
                    len(sitemap_urls),
                    len(scraped_urls),
                    args.count
                )
                if not should_scrape:
                    logging.info("Scraping cancelled by user")
                    return
            else:
                # --yes flag: use count from args or default to all
                if args.count:
                    if args.count.lower() == 'all':
                        scrape_count = None
                    else:
                        try:
                            scrape_count = int(args.count)
                            scrape_count = min(scrape_count, len(new_festivals))
                        except ValueError:
                            logging.error(f"Invalid count '{args.count}'. Must be a number or 'all'")
                            return
                else:
                    scrape_count = None  # Default to all

            # Scrape new festivals
            festivals_data = scrape_festival_details(new_festivals, scrape_count)

            logging.info("=" * 80)
            logging.info(f"Scraping completed! Scraped {len(festivals_data)} festivals successfully.")
            logging.info("=" * 80)
        else:
            logging.info("=" * 80)
            logging.info("All festivals already scraped! Nothing to do.")
            logging.info("=" * 80)

    except KeyboardInterrupt:
        logging.info("\nScraping interrupted by user")
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}", exc_info=True)
        raise


if __name__ == '__main__':
    main()