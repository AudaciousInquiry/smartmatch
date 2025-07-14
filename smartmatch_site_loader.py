from loguru import logger
from langchain_core.documents import Document
#from langchain_community.document_loaders import WebBaseLoader
from langchain_unstructured import UnstructuredLoader

class SmartMatchSiteLoader:
    def __init__(self, site_name):
        self.site_name = site_name
        self.loader = UnstructuredLoader(web_url=site_name)

    def load_site(self) -> list[Document]:
      logger.info(f"Loading site: {self.site_name}")
      docs = self.loader.load()
      return docs
    