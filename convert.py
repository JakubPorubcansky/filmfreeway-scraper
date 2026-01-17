import pandas as pd
import json
import glob
import os


def read_jsonl_to_dataframe(filepath):
    data = []

    with open(filepath, 'r', encoding='utf-8') as file:
        for idx, line in enumerate(file):
            if line.strip():
                try:
                    record = json.loads(line)
                    row = {
                        'url': record['url'],
                    }
                    if 'title' in record:
                        row['title'] = record['title']

                    if 'sections' in record:
                        for section in record['sections']:
                            col_name = section['title'] if section['title'] else "About"
                            row[col_name] = section['content']

                    if 'dates_deadlines' in record:
                        for dd in record['dates_deadlines']:
                            if 'deadline_type' in dd and dd['deadline_type'] == 'Event Date':
                                row['Event Date'] = dd['date']
                                row['Event Datetime'] = dd['datetime']
                                row['Event Status'] = dd['status']

                    data.append(row)
                except json.JSONDecodeError as e:
                    print(f"Warning: Skipping invalid JSON line: {e}")
                    continue

    df = pd.DataFrame(data)
    return df


def read_all_jsonl_to_dataframe(scraped_dir='scraped'):
    """Read all festivals_data_*.jsonl files and combine into one DataFrame."""
    all_data = []

    # Find all matching files
    pattern = os.path.join(scraped_dir, 'festivals_data_*.jsonl')
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No JSONL files found in {scraped_dir}")
        return pd.DataFrame()

    print(f"Found {len(files)} JSONL file(s) to convert:")

    for filepath in files:
        print(f"  Reading {os.path.basename(filepath)}...")
        df = read_jsonl_to_dataframe(filepath)
        all_data.append(df)

    # Combine all dataframes
    combined_df = pd.concat(all_data, ignore_index=True)
    print(f"Total festivals: {len(combined_df)}")

    return combined_df


def find_next_output_filename(output_dir='output', base_name='output', extension='.csv'):
    """Find the next available output filename (output_1.csv, output_2.csv, etc.)."""
    os.makedirs(output_dir, exist_ok=True)

    num = 1
    while True:
        filename = os.path.join(output_dir, f"{base_name}_{num}{extension}")
        if not os.path.exists(filename):
            return filename
        num += 1


if __name__ == "__main__":
    # Read all JSONL files
    df = read_all_jsonl_to_dataframe('scraped')

    if df.empty:
        print("No data to convert!")
    else:
        # Find next available output filename
        output_path = find_next_output_filename()

        # Save to CSV
        df.to_csv(output_path, index=False)
        print(f"\nSaved to: {output_path}")