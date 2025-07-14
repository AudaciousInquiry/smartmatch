from loguru import logger

from langchain_postgres import PGVector
from configuration_values import ConfigurationValues
from smartmatch_embeddings import SmartMatchEmbeddings

class TestCollectionVectorStore(PGVector):
    def __init__(self):
      logger.info("Initializing TestCollectionVectorStore")
      super().__init__(collection_name="rfps",
          embeddings=SmartMatchEmbeddings.create_embeddings(),
          connection=ConfigurationValues.get_pgvector_connection(),
          use_jsonb=True,
      )