from langchain_core.prompts import ChatPromptTemplate

def get_prompt() -> ChatPromptTemplate:

  template = """Use the following pieces of context to answer the question at the end. 
    If you don't know the answer, just say that you don't know, don't try to make up an answer.
    Context: {context}

    Question: {question}
  """
  prompt = ChatPromptTemplate.from_template(template)
  return prompt

def get_competency_match_prompt(competencies_as_string: str) -> ChatPromptTemplate:

  template = """Use the following pieces of context to answer the question at the end. 
    If you don't know the answer, just say that you don't know, don't try to make up an answer.
    Context: {context}

    Competencies: {competencies}

    Question: {question}
  """
  prompt = ChatPromptTemplate.from_template(template, partial_variables={"competencies":competencies_as_string})
  return prompt
