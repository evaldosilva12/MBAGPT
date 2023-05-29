import os
from langchain.document_loaders import DirectoryLoader, PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.chains.question_answering import load_qa_chain
from langchain.llms import OpenAI
from langchain.chains import ConversationalRetrievalChain

os.environ["OPENAI_API_KEY"] = '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'

# Set persist directory
persist_directory = 'db'

buffett_loader = DirectoryLoader('./docs/buffett/', glob="*.pdf")
branson_loader = DirectoryLoader('./docs/branson/', glob="*.pdf")
web_loader     = DirectoryLoader('./docs/web/', glob="*.txt")

buffett_docs = buffett_loader.load()
branson_docs = branson_loader.load()
web_docs     = web_loader.load()

embeddings = OpenAIEmbeddings()
text_splitter = CharacterTextSplitter(chunk_size=750, chunk_overlap=8)

# Split documents and generate embeddings
buffett_docs_split = text_splitter.split_documents(buffett_docs)
branson_docs_split = text_splitter.split_documents(branson_docs)
web_docs_split     = text_splitter.split_documents(web_docs)

# Create Chroma instances and persist embeddings
buffettDB = Chroma.from_documents(buffett_docs_split, embeddings, persist_directory=os.path.join(persist_directory, 'buffett'))
buffettDB.persist()

bransonDB = Chroma.from_documents(branson_docs_split, embeddings, persist_directory=os.path.join(persist_directory, 'branson'))
bransonDB.persist()

webDB = Chroma.from_documents(web_docs_split, embeddings, persist_directory=os.path.join(persist_directory, 'web'))
webDB.persist()
