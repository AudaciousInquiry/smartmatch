from bs4 import BeautifulSoup
from loguru import logger

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_aws import ChatBedrock
import requests

from chains import get_competency_check_chain, get_default_chain
from configuration_values import ConfigurationValues
from competencies import get_competencies;
from cdc_foundation import load_site
from prompts import get_prompt, get_competency_match_prompt

# --- SCRAPER FUNCTIONS --- this can be moved to a separate file maybe siteloader
def scrape_cdc_foundation(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    rfps = []
    # add logic to scrape the CDC Foundation site...

    return rfps

def scrape_cste(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    rfps = []
    # add logic to scrape the CSTE site...
    return rfps

def scrape_nnphi(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    rfps = []
   # add logic to scrape the NNPHI site...
    return rfps

# --- SCRAPER MAP ---
SCRAPER_MAP = {
    "cdcfoundation": scrape_cdc_foundation,
    "cste": scrape_cste,
    "nnphi": scrape_nnphi,
}

def main():
  logger.info("Initializing vector store")
  vector_store = PGVector(
          embeddings=HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2"),
          collection_name="rfps",
          connection=ConfigurationValues.get_pgvector_connection(),
          use_jsonb=True,
  )
  input("Press any key continue...")
# some initial logic to load rfps from websites and add to vector store
  logger.info("Loading RFPs from websites")
  all_new_rfps = []
  for site in ConfigurationValues.get_websites():
      scraper = SCRAPER_MAP[site["name"]]
      rfps = scraper(site)
      for rfp in rfps:
          try:
                  vector_store.add_texts([rfp['title']], metadatas=[{"url": rfp['url'], "site": rfp['site']}])
                  all_new_rfps.append(rfp)
          except Exception as e:
                  if "duplicate key value violates unique constraint" in str(e):
                      continue
                  print(f"Error adding RFP '{rfp['title']}' from {rfp['site']}: {e}")

  if all_new_rfps:
        print("New RFPs found:")
        for r in all_new_rfps:
            print(f"{r['site']}: {r['title']} ({r['url']})")
  else:
        print("No new RFPs found.")
  #source_url = load_site()
  
  ''' chain = get_default_chain(get_prompt(), vector_store, get_chat_model(), source_url)
  response = chain.invoke("""Provide a summary of the document and its contents focusing on technical requirements found in the document. 
                          In the summary highlight any dates, deadlines, or timelines mentioned in the document. Also, provide any dollar 
                          amounts if mentioned.""")
  logger.info(f"Response: {response['answer']}")
  
  input("Press any key continue...")
  competencies = get_competencies(vector_store)
  competency_match_chain = get_competency_check_chain(get_competency_match_prompt(competencies), vector_store, get_chat_model(), source_url)

  input("Press any key continue...")
  response = competency_match_chain.invoke("On a scale of 1-10, do you think this aligns with the competencies listed below and should Audacious Inquiry bid on on the project and provide reasons.")
  logger.info(f"Response: {response['answer']}")
  
def get_chat_model() -> ChatBedrock:
  return ChatBedrock(model_id="us.meta.llama3-3-70b-instruct-v1:0",
          max_tokens=1024,
          temperature=0.0,
        )
 '''
main()

