from langchain_community.embeddings import BedrockEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings

from configuration_values import ConfigurationValues

class SmartMatchEmbeddings:

  def create_embeddings():
    # Create embeddings using the specified model
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    #return BedrockEmbeddings(
    #  model_id=ConfigurationValues.get_embeddings_model(), 
    #  region_name=ConfigurationValues.get_aws_region_name(),
    #)
