from pathlib import Path
import hashlib
import pandas as pd
from .retrieval.db_connector import dbConnector
from .classes.ollama_connector import OllamaConnector
from dotenv import load_dotenv
import os
load_dotenv()

current_model = os.getenv('EMBED_MODEL_NAME')

type = 'source' # 'source' or 'claim'

input_file= './data/enriched_sources_merges.jsonl' if type == 'source' else './data/claims_canonical.jsonl'


MODELS = dbConnector.MODELS

index_name = 'claims_index' if type == 'claim' else 'sources_index'

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


def stable_id_for_claim(record: dict) -> str:
	# Prefer an existing canonical claim id if present (e.g., "C81" or "AUTO_CLAIM_93")
	for key in ("claim_id", "id", "claimId"):
		val = record.get(key)
		if isinstance(val, str) and val.strip():
			return val.strip()
	# Fallback: hash the English protocol claim
	text = (record.get("protocol_claim_en") or "").strip()
	return "claim:" + hashlib.sha1(text.encode("utf-8")).hexdigest()


def stable_id_for_source(row: dict) -> str:
	pmid = row.get("pmid")
	doi = row.get("doi")	
	url = row.get("url")
	# Prefer stable natural keys when available
	if pmid:
		return f"pmid:{str(pmid).strip()}"
	if doi:
		return f"doi:{str(doi).strip().lower()}"
	if url:
		return "url:" + hashlib.sha1(str(url).strip().encode("utf-8")).hexdigest()
	# Last resort: hash title + content
	title = (row.get("title") or "").strip()
	content = (row.get("content_for_embedding") or "").strip()
	return "src:" + hashlib.sha1((title + "\n" + content).encode("utf-8")).hexdigest()


def build_claim_document(row):
		record = row.copy()
		record['index'] = index_name
		record['embedding'] = OllamaConnector.embed_text(record['protocol_claim_en'])
		record['content_for_embedding'] = record['protocol_claim_en']
		record['created_at'] = pd.Timestamp.now().isoformat()
		record['id'] = stable_id_for_claim(record)
		return record


def build_source_document(row):
		if len(row['content_for_embedding']) < 50:
			print (f"Skipping record with insufficient content for embedding: PMID {row['pmid']}, DOI {row['doi']}")
			return False
		record = {
			'id': stable_id_for_source(row),
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
