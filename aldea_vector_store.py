from loguru import logger

from langchain_postgres import PGVector
from configuration_values import ConfigurationValues
from aldea_embeddings import AldeaEmbeddings

class TestCollectionVectorStore(PGVector):
    def __init__(self):
      logger.info("Initializing TestCollectionVectorStore")
      super().__init__(collection_name="Aldea",
          embeddings=AldeaEmbeddings.create_embeddings(),
          connection=ConfigurationValues.get_pgvector_connection(),
          use_jsonb=True,
      )