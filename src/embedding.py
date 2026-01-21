from pathlib import Path
import pandas as pd
from classes.db_connector import dbConnector
from uuid import uuid7
from classes.ollama_connector import OllamaConnector
from dotenv import load_dotenv
import os
load_dotenv()

current_model = os.getenv('MODEL_NAME')

type = 'claim' # 'source' or 'claim'

input_file= './data/enriched_sources_20260113_1520_cleaned.jsonl' if type == 'source' else './data/claims_canonical.jsonl'


MODELS = dbConnector.MODELS

index_name = 'claims_index' if type == 'claim' else 'source_index'

db = dbConnector()

source_file = Path(input_file)
data = pd.read_json(source_file, lines=True)

def convert_row(row):
    d = row.to_dict()
    out = {}
    for k, v in d.items():
        # Do NOT apply pd.isna to list-like values
        if isinstance(v, (list, dict)):
            out[k] = v
        else:
            out[k] = None if pd.isna(v) else v
    return out


def build_claim_document(row):
		record = row.copy()
		record['index'] = index_name
		record['embedding'] = OllamaConnector.embed_text(record['protocol_claim_en'])
		record['content_for_embedding'] = record['protocol_claim_en']
		record['created_at'] = pd.Timestamp.now().isoformat()
		record['id'] = str(uuid7())
		return record


def build_source_document(row):
		if len(row['content_for_embedding']) < 50:
			print (f"Skipping record with insufficient content for embedding: PMID {row['pmid']}, DOI {row['doi']}")
			return False
		record = {
			'id': str(uuid7()),
			'index': index_name,
			'source_type': row['source_type'],
			'pmid': row['pmid'],
			'doi': row['doi'],
			'title': row['title'],
			'content_for_embedding':row['content_for_embedding'],
			'claim_ids': row['claim_ids'],
			'tags': row['tags'],
			'abstract_source': row['abstract_source'],
			'url': row['url'],
			'embedding': OllamaConnector.embed_text(row['content_for_embedding'])
		}
		return record

db.create_index(index_name)

build_document = build_claim_document if type == 'claim' else build_source_document
errors = []
skipped = 0
for index, row in data.iterrows():
	try:
		if index % 5 == 0:
			print(f"Processing record {index}/{len(data)}")
		converted_row = convert_row(row)
		document = build_document(converted_row)
		if document:
			db.index_to_db(index_name, document)
			print(f"Indexed record {index} with ID {document['id']}")
		else:
			skipped += 1
			print(f"Skipped record {index}")
	except Exception as e:
		print(f"Error processing record {index}: {e}")
		errors.append((index, str(e)))

print(f"Completed embedding and indexing. Total records: {len(data)}, Skipped: {skipped}, Errors: {len(errors)}")
print(errors)		


