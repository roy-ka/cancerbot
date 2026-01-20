import pandas as pd
import opensearchpy as op
from pathlib import Path
from uuid import uuid7

p = Path('./data/')
TYPES= {
    'news': 'News Article',
    'article': 'Research Article',
    'wikipedia': 'Wikipedia Entry',
}
sources = []

source_template = {
        'id': str(uuid7()),
        'file_path': '',
        'type': '',
        'title': '',
        'text': '',
        'type': '',
        'link': '',
        'file_source': '',
        'pmid': '',
        'doi': ''
    }

def create_source(record): 
  return {**source_template, **record}

def build_source(record, file_path):
    arr = []
    if record.get('key_evidence'):
        for entry in record['key_evidence']:
            ev={'file_path': file_path,
                'title': record.get('title',''),
                'text': entry.get('text',''),
                'type': TYPES.articles,
                'link': entry.get('link',''),
                'file_source': record.get('file_source',''),
                'pmid': entry.get('pmid',''),
                'doi': entry.get('doi','')}
            arr.append(create_source(ev))
    # if record.get('wikipedia_sources')
    return arr

def parse_data(data,file_path ):
    print(f"Parsing data {file_path}")
    print(data.columns)
    return data

def loadJsonlData(file_path):
    data = pd.read_json(file_path, lines=True)
    return data

for file in p.rglob('*.jsonl'):
    sources.extend(loadJsonlData(file))

print(f"Loaded {len(sources)} records from data files.")