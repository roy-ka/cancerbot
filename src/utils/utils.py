import urllib.request
from bs4 import BeautifulSoup
import json
import pandas as pd
from dotenv import load_dotenv
import os


pubmed_api_base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
crossref_api_url = "https://api.crossref.org/works?select=DOI,abstract&rows=1&filter=has-abstract:1,doi:"
load_dotenv()

ENV = os.getenv('ENV')
def send_request(url):
  req = urllib.request.Request(url,data=None, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
            })
  try:
    res = urllib.request.urlopen(req).read()
    parser = 'xml' if pubmed_api_base_url in url else 'html.parser'
    print(f"Fetched URL: {url}, parser used: {parser}")
    return BeautifulSoup(res, parser)
  except Exception as e:
    print(f"Error fetching URL {url}: {e}")
    raise e
  
def write_to_file(filepath, data):
  with open(filepath, 'w') as f:
    for record in data:
      f.write(json.dumps(record, ensure_ascii=False) + '\n')  

def is_exist(field):
  return field and not pd.isna(field) and field != '' and field != 'NA' and field != 'N/A' and field != 'null' and field != 'None'

def is_prod():
  return ENV.lower() == 'prod' or ENV.lower() == 'production'