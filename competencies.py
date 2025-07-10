from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_postgres import PGVector
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_aws import ChatBedrock
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from sqlalchemy import create_engine, Table, MetaData, delete
from loguru import logger

from configuration_values import ConfigurationValues


def get_competencies(vector_store: PGVector):
  
  vector_store = PGVector(
          embeddings=HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2"),
          collection_name="Aldea",
          connection=ConfigurationValues.get_pgvector_connection(),
          use_jsonb=True,
      )  
  
  docs = get_documents("c:\\files\\3.pdf", "3.pdf")
  store_vectors(vector_store, docs, "3.pdf")
  docs = get_documents("c:\\files\\4.pdf", "4.pdf")
  store_vectors(vector_store, docs, "4.pdf")
  
  chain = get_chain(get_prompt(), vector_store, get_chat_model())
  response = chain.invoke("""Determine a list of compentencies for Audacious Inquiry based on the existing proposals.""")
  logger.info(f"Response: {response['answer']}")
  return response['answer']
  
def store_vectors(vector_store, docs, source):
  deleted_count = delete_by_metadata({"source": source})
  vector_store.add_documents(docs)

def get_documents(path_to_file: str, source: str):
  loader = PyPDFLoader(path_to_file)
  docs = loader.load_and_split(RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""]
  ))
  
  #Add metadata to each document
  for doc in docs:
    doc.metadata["source"] = source
    doc.metadata["ai_docs"] = True
  
  return ([Document(page_content=doc.page_content, metadata = doc.metadata) for doc in docs])

def get_chain(prompt: ChatPromptTemplate, vector_store: PGVector, chat_model: ChatBedrock) -> RunnablePassthrough:
  logger.info("Creating default chain")
  retriever = vector_store.as_retriever(search_kwargs={"k": 20, "filter":{"ai_docs":True}})

  rag_chain_from_docs = (
    RunnablePassthrough.assign(context=(lambda x: format_docs(x["context"])))
    | prompt
    | chat_model
    | StrOutputParser()
  )

  rag_chain_with_source = RunnableParallel(
    {"context": retriever, "question": RunnablePassthrough()}
  ).assign(answer=rag_chain_from_docs)
  
  return rag_chain_with_source

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

def get_prompt() -> ChatPromptTemplate:

  template = """Use the following pieces of context to answer the question at the end. 
    If you don't know the answer, just say that you don't know, don't try to make up an answer.
    Context: {context}

    Question: {question}
  """
  prompt = ChatPromptTemplate.from_template(template)
  return prompt

def get_chat_model() -> ChatBedrock:
  return ChatBedrock(model_id="us.meta.llama3-3-70b-instruct-v1:0",
          max_tokens=1024,
          temperature=0.0,
        )

def format_docs(docs):
  return "\n\n".join(doc.page_content for doc in docs)
