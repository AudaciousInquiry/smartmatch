from loguru import logger
from langchain_core.prompts import ChatPromptTemplate
from langchain_aws import ChatBedrock
from langchain_postgres import PGVector
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser

def get_default_chain(prompt: ChatPromptTemplate, vector_store: PGVector, chat_model: ChatBedrock, source: str) -> RunnablePassthrough:
  retriever = vector_store.as_retriever(search_kwargs={"k": 20, "filter":{"source":source}})
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

def get_competency_check_chain(prompt: ChatPromptTemplate, vector_store: PGVector, chat_model: ChatBedrock, source: str) -> RunnablePassthrough:
  retriever = vector_store.as_retriever(search_kwargs={"k": 20, "filter":{"ai_docs":True}})
  #retriever = vector_store.as_retriever(search_kwargs={"k": 20, "filter":{"source":source}})
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

def format_docs(docs):
  return "\n\n".join(doc.page_content for doc in docs)
