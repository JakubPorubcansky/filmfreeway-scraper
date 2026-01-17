import pandas as pd
import json

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


# Example usage
if __name__ == "__main__":
    df = read_jsonl_to_dataframe('scraped/festivals_data_2.jsonl')
    df.to_csv('output/output2.csv', index=False)