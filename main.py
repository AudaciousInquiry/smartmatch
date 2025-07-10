from loguru import logger

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_aws import ChatBedrock

from chains import get_competency_check_chain, get_default_chain
from configuration_values import ConfigurationValues
from competencies import get_competencies;
from cdc_foundation import load_site
from prompts import get_prompt, get_competency_match_prompt


def main():
  logger.info("Initializing vector store")
  vector_store = PGVector(
          embeddings=HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2"),
          collection_name="Aldea",
          connection=ConfigurationValues.get_pgvector_connection(),
          use_jsonb=True,
  )
  input("Press any key continue...")
  source_url = load_site()
  
  chain = get_default_chain(get_prompt(), vector_store, get_chat_model(), source_url)
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

main()

