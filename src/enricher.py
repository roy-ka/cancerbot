from pathlib import Path
import pandas as pd
import re 
import json
from src.utils.utils import send_request, pubmed_api_base_url, write_to_file,crossref_api_url, isExsit
import wikipedia

pubmed_api_efetch_url = pubmed_api_base_url +'efetch.fcgi?db=pubmed&id='#&rettype=["abstract","doi"]
pubmed_api_esearch_url= lambda doi : pubmed_api_base_url+ f'esearch.fcgi?db=pubmed&term={doi}[DOI]&retmode=xml'
patent_reg = re.compile(r"[A-Z]{2}/?\d{4}/?\d{6}?[A-Z]?\d", re.MULTILINE)
source_file = Path('./data/sources_for_embedding.jsonl')
ouptput_file = Path(f'./data/enriched_sources_{pd.Timestamp.now().__format__('%Y%m%d_%H%M')}.jsonl')
data = pd.read_json(source_file, lines=True)
print(f"Loaded {len(data)} records from {source_file}")   
enrichedData = []
pmids=[]
dois=[]
errors = 0

def send_request_wrapper(url):
  try:
    return send_request(url)
  except Exception as e:
    global errors
    errors += 1
    print(f"Error in send_request_wrapper for URL {url}: {e}")
    return None

def fetchDataFromPubmed(pmid):
  if not isExsit(pmid): return None 
  url = f"{pubmed_api_efetch_url}{pmid}"
  soup = send_request_wrapper(url)
  if soup:
    article = soup.PubmedArticleSet.PubmedArticle.MedlineCitation.Article
    res = {}
    res['abstract_text'] = article.Abstract.get_text(separator=' ', strip=True) if article.Abstract else None
    res['doi'] = article.Dois.Doi.get_text(strip=True) if article.Dois else None
    return res
  return None

empty_abstract_count = 0
for index, row in data.iterrows():
  enriched_record = row.to_dict()
  if not isExsit(enriched_record['abstract']):
    empty_abstract_count += 1 
    if isExsit(enriched_record['pmid']):
      if enriched_record['pmid'] in pmids:
        continue
      pmids.append(enriched_record['pmid'])
      if isExsit(enriched_record['doi']) and enriched_record['doi'] not in dois:
        dois.append(enriched_record['doi'])
      response = fetchDataFromPubmed(enriched_record['pmid'])
      if response:
        enriched_record["abstract_source"] ='PubMed'
        enriched_record['abstract_fetched_at']= pd.Timestamp.now().isoformat()
        enriched_record['abstract'] = response['abstract_text']
        if not isExsit(enriched_record['doi']):
          enriched_record['doi'] = response['doi']
    if isExsit(enriched_record['doi']):
      if enriched_record['doi'] in dois:
        continue
      pubmed_doi_url = pubmed_api_esearch_url(enriched_record['doi'])
      dois.append(enriched_record['doi'])
      pubmed_doi_soup = send_request_wrapper(pubmed_doi_url)
      if pubmed_doi_soup:
        if pubmed_doi_soup.eSearchResult and pubmed_doi_soup.eSearchResult.Id:
          enriched_record['pmid'] = pubmed_doi_soup.eSearchResult.Id.get_text(strip=True)
        else:
          enriched_record['pmid'] = None  # Or assign a default value or log an error
        dois.append(enriched_record['doi'])
        if enriched_record['pmid'] not in pmids:
          pmids.append(enriched_record['pmid'])
        response = fetchDataFromPubmed(enriched_record['pmid'])
        if response:
          enriched_record["abstract_source"] ='PubMed'
          enriched_record['abstract_fetched_at']= pd.Timestamp.now().isoformat()
          enriched_record['abstract'] = response['abstract_text']
    if not isExsit(enriched_record['abstract']): #not found any abstract so far: 
      if isExsit(enriched_record['doi']):
        crossref_url = f"{crossref_api_url}{enriched_record['doi']}"
        crossref_soup = send_request_wrapper(crossref_url)
        if crossref_soup:
          crossref_data = json.loads(crossref_soup.get_text(separator=' ', strip=True))
          if crossref_data['status'] == 'ok':
            message = crossref_data['message']
            if message and message['total-results'] > 0:
              abstract_text = message['items'][0]['abstract']
              if isExsit(abstract_text):
                enriched_record["abstract_source"] ='CrossRef'
                enriched_record['abstract_fetched_at']= pd.Timestamp.now().isoformat()
                enriched_record['abstract'] = abstract_text
      elif enriched_record['source_type'] != 'wikipedia':
        print(f"No DOI available for record index {index}, skipping CrossRef lookup.")
        print(f"Record details: {enriched_record}")
    if re.search(patent_reg,row['title']):
      enriched_record["abstract_source"] ='Patent'
      enriched_record['abstract_fetched_at']= pd.Timestamp.now().isoformat()
      enriched_record['abstract'] = 'Patent document. Abstract not fetched.'
    if enriched_record['source_type'] == 'wikipedia':
      print (f"Fetching Wikipedia abstract for title: {enriched_record['title']}")
      enriched_record["abstract_source"] ='Wikipedia'
      enriched_record['abstract_fetched_at']= pd.Timestamp.now().isoformat()
      enriched_record['abstract'] = wikipedia.summary(enriched_record['title'],sentences=10)

  enriched_record['content_for_embedding'] =(enriched_record.get('title','') or '')+ "\n\n"+ (enriched_record.get('abstract','') or "")
  enrichedData.append(enriched_record)

write_to_file(ouptput_file, enrichedData)
print(f"Total records with empty abstracts: {empty_abstract_count}")
print(f"Enriched data saved to {ouptput_file} with {len(enrichedData)} records. Total errors: {errors}")