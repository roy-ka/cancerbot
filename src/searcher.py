from src.utils.utils import send_request, pubmed_api_base_url, write_to_file, crossref_api_url, is_exist
from src.xml_to_source import pubmed_article_xml_to_source
import pandas as pd
from pathlib import Path
import json

pubmed_api_esearch_url = pubmed_api_base_url +'esearch.fcgi?db=pubmed&retmode=xml&usehistory=y&term=cancer'
pubmed_api_efetch_url = pubmed_api_base_url +'efetch.fcgi?db=pubmed&id='
response_soup = send_request(pubmed_api_esearch_url)

ids = []
for id in response_soup.IdList.children:
  ids.append(id.get_text(strip=True))

url = f"{pubmed_api_efetch_url}{','.join(ids)}&rettype=abstract"
fetch_soup = send_request(url)
with_abstract = []
without_abstract = []
for article in fetch_soup.find_all('PubmedArticle'):
  #/PubmedArticle/MedlineCitation/Article/Abstract/AbstractText
  core_article = article.MedlineCitation.Article
  if core_article.Abstract is None:
    without_abstract.append(core_article)
    continue
  with_abstract.append(core_article)
  
sources = []
for article in with_abstract:
  source = pubmed_article_xml_to_source(article)
  sources.append(source)

for article in without_abstract:
  if (article.find('ELocationID', {'EIdType':'doi'})):
        crossref_url = f"{crossref_api_url}{article.find('ELocationID', {'EIdType':'doi'}).get_text(strip=True)}"
        crossref_soup = send_request(crossref_url)
        if crossref_soup:
          crossref_data = json.loads(crossref_soup.get_text(separator=' ', strip=True))
          if crossref_data['status'] == 'ok':
            message = crossref_data['message']
            if message and message['total-results'] > 0:
              abstract_text = message['items'][0]['abstract']
              if is_exist(abstract_text):
                article["abstract_source"] ='CrossRef'
                article['abstract_fetched_at']= pd.Timestamp.now().isoformat()
                article['abstract'] = abstract_text


ouptput_file = Path(f'./data/enriched_sources_{pd.Timestamp.now().__format__('%Y%m%d_%H%M')}.jsonl')
write_to_file(ouptput_file, sources)
