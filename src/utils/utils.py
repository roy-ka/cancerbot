import urllib.request
from bs4 import BeautifulSoup
import json
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

# A tuple, not a set: `in` on a set hashes the operand, which would raise
# TypeError for the unhashable values (lists) that can reach this check.
_MISSING_VALUES = ('', 'NA', 'N/A', 'null', 'None')


def is_exist(field):
  """True when `field` holds a real value rather than a null-ish placeholder.

  Deliberately pandas-free: this module is imported by main.py, auth.py and
  db_connector.py, so a module-level `import pandas` pulled pandas + numpy
  (~100MB resident) into every backend and worker process for this one check.
  `field != field` is the NaN test pd.isna() was doing for float values.
  """
  if not field or field != field:
    return False
  return field not in _MISSING_VALUES

def is_prod():
  return (ENV or '').lower() in ('prod', 'production')


def dev_email_shortcuts():
  """Local-dev convenience: /auth/register/ and /auth/request-code/ return
  the sign-in code in their response (`dev_code`) and the login screen shows
  it, so local development and E2E need no inbox. Opt-in via
  DEV_EMAIL_SHORTCUTS rather than implied by non-production, because a code
  in the response is a login for that account — on staging it would let
  anyone sign in as anyone. Never active in production (main.py also refuses
  to start with it set there). Read per call so tests can monkeypatch it."""
  if is_prod():
    return False
  return os.getenv('DEV_EMAIL_SHORTCUTS', '').strip().lower() in ('1', 'true', 'yes')