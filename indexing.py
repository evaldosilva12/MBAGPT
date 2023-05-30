import os
from langchain.document_loaders import DirectoryLoader, PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.chains.question_answering import load_qa_chain
from langchain.llms import OpenAI
from langchain.chains import ConversationalRetrievalChain
import streamlit as st


os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

# Set persist directory
persist_directory = 'db'

pdf_loader  = DirectoryLoader('./docs/pdf/', glob="*.pdf")
web_loader  = DirectoryLoader('./docs/web/', glob="*.txt")

pdf_docs = pdf_loader.load()
web_docs = web_loader.load()

embeddings      = OpenAIEmbeddings()
text_splitter   = CharacterTextSplitter(chunk_size=1024, chunk_overlap=8)

# Split documents and generate embeddings
pdf_docs_split  = text_splitter.split_documents(pdf_docs)
web_docs_split  = text_splitter.split_documents(web_docs)

# Create Chroma instances and persist embeddings
pdfDB = Chroma.from_documents(pdf_docs_split, embeddings, persist_directory=os.path.join(persist_directory, 'pdf'))
pdfDB.persist()

webDB = Chroma.from_documents(web_docs_split, embeddings, persist_directory=os.path.join(persist_directory, 'web'))
webDB.persist()
