from loguru import logger
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from sqlalchemy import create_engine, Table, MetaData, delete

from aldea_site_loader import AldeaSiteLoader
from configuration_values import ConfigurationValues


def load_site() -> str:
  site_loader = AldeaSiteLoader("https://www.cdcfoundation.org/request-for-proposals")
  docs = site_loader.load_site()
  html_docs = list(filter(lambda doc: doc.page_content == "View RFQ", docs))

  logger.info(f"View RFQ link count: {len(html_docs)}")
  
  text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""]
  )

  source_url = html_docs[0].metadata['link_urls'][0]

  loader = PyPDFLoader(source_url)
  pdf_docs = loader.load_and_split(text_splitter)
  
  vector_store = PGVector(
          embeddings=HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2"),
          collection_name="Aldea",
          connection=ConfigurationValues.get_pgvector_connection(),
          use_jsonb=True,
      )  
  deleted_count = delete_by_metadata({"source": source_url})
  vector_store.add_documents(pdf_docs)  

  return source_url
  
def delete_by_metadata(metadata_filter: dict) -> int:
    """
    Delete rows from a PGVector table based on metadata.

    Args:
        connection_string: SQLAlchemy connection string to Postgres.
        table_name: The PGVector table name.
        metadata_filter: Dictionary of metadata to filter by (e.g., {"category": "langchain"}).

    Returns:
        The number of rows deleted.
    """
    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    metadata = MetaData(schema="public")
    conn = engine.connect()

    doc_table = Table("langchain_pg_embedding", metadata, autoload_with=engine)

    if 'cmetadata' not in doc_table.columns:
        raise ValueError(f"'cmetadata' column not found in table 'langchain_pg_embedding'. Available columns: {doc_table.columns.keys()}")

    # Build WHERE clause from metadata
    conditions = [
        doc_table.c.cmetadata[key].astext == str(value)
        for key, value in metadata_filter.items()
    ]

    delete_stmt = delete(doc_table).where(*conditions)
    result = conn.execute(delete_stmt)
    conn.commit()
    conn.close()

    return result.rowcount
