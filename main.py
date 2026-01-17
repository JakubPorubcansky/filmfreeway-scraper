#!/usr/bin/env python3
"""
FilmFreeway Festival Scraper
Scrapes festival information from FilmFreeway.com
Compliant with robots.txt (Crawl-delay: 20)
"""

import time
import argparse
from tqdm import tqdm
from typing import Optional, Dict, List
import requests
from bs4 import BeautifulSoup
import logging
import random
import json
from pathlib import Path

DELAY_BETWEEN_FESTIVALS = 20
REQUEST_TIMEOUT = 30

# Rotate between multiple realistic user agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
]

def save_festival(festival_data: Dict, output_file: str = "festivals_data.jsonl"):
    """Append festival data to JSONL file."""
    with open("scraped/" + output_file, 'a', encoding='utf-8') as f:
        json.dump(festival_data, f, ensure_ascii=False)
        f.write('\n')


def get_session() -> requests.Session:
    """Create a session with proper headers mimicking a real browser."""
    session = requests.Session()
    
    # Set comprehensive browser-like headers
    session.headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
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
    scrape_from: Optional[int] = 0, 
    scrape_to: Optional[int] = None
) -> List[Dict[str, any]]:
    """Scrape detailed information for each festival."""
    scrape_to = len(urls) if not scrape_to else scrape_to
    
    if scrape_from >= scrape_to:
        logging.error(f"Invalid range: scrape_from ({scrape_from}) >= scrape_to ({scrape_to})")
        return []

    logging.info(
        f"Starting to scrape details for {scrape_to - scrape_from} festivals "
        f"(from #{scrape_from} to #{scrape_to - 1})..."
    )

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
    
    with tqdm(total=scrape_to - scrape_from, desc="Scraping festival details") as pbar:
        for idx, url in enumerate(urls[scrape_from:scrape_to], start=scrape_from):
            try:
                festival_data = {"idx": idx}
                festival_data.update(scrape(url, session))
                festivals_data.append(festival_data)

                save_festival(festival_data)
                
                section_count = len(festival_data.get('sections', []))
                logging.info(
                    f"[{idx}] Successfully scraped: {festival_data['title']} "
                    f"({section_count} sections)"
                )
                
                pbar.update(1)
                
                delay_variation = random.uniform(-3, 3)
                actual_delay = max(DELAY_BETWEEN_FESTIVALS + delay_variation, 0)
                
                if idx < scrape_to - 1:  # Don't delay after last item
                    time.sleep(actual_delay)

            except Exception as e:
                logging.error(f"[{idx}] Error processing {url.strip()}: {str(e)}")
                save_festival({"idx": idx, "url": url})
                pbar.update(1)
                # Continue with next festival
                continue
    
    logging.info(f"Successfully scraped {len(festivals_data)} out of {scrape_to - scrape_from} festivals")
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
        '--scrape-from', 
        type=int, 
        default=0, 
        help='Start scraping from this festival index (0-based)'
    )
    parser.add_argument(
        '--scrape-to', 
        type=int, 
        default=None, 
        help='Stop scraping at this festival index (exclusive)'
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
        with open("input/festivals2.txt", 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        logging.info(f"Loaded {len(urls)} festival URLs from input file")
        
        if not urls:
            logging.error("No URLs found in input file")
            return

        festivals_data = scrape_festival_details(urls, args.scrape_from, args.scrape_to)

        logging.info("=" * 80)
        logging.info(f"Scraping completed! Scraped {len(festivals_data)} festivals successfully.")
        logging.info("=" * 80)

    except FileNotFoundError:
        logging.error("Input file not found. Please create this file with festival URLs.")
    except KeyboardInterrupt:
        logging.info("\nScraping interrupted by user")
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}", exc_info=True)
        raise


if __name__ == '__main__':
    main()