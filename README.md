# FilmFreeway Festival Scraper

Scrapes festival information from FilmFreeway.com and converts to CSV.

## Setup (only first time)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

## Usage

### 1. Scrape festivals

```bash
source venv/bin/activate && python main.py
```

The script will ask:
- Do you want to start scraping? (yes/no)
- How many festivals to scrape? (enter number or 'all')

Or skip prompts:
```bash
python main.py --count 50 --yes     # Scrape 50 festivals
python main.py --count all --yes    # Scrape all new festivals
```

Data is saved to `scraped/festivals_data_*.jsonl` (10,000 entries per file).

### 2. Convert to CSV

```bash
source venv/bin/activate && python convert.py
```

Output: `output/output_*.csv`
