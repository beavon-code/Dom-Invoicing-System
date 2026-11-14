from dotenv import load_dotenv
import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
    CSVLoader,
    UnstructuredExcelLoader,
    UnstructuredPowerPointLoader,
)


load_dotenv()

Path("Uploads").mkdir(exist_ok=True)
Path("Chroma_db").mkdir(exist_ok=True)


# Embedding model
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

vectorstore = Chroma(
    collection_name="erp_chatbot_docs",
    embedding_function=embeddings,
    persist_directory="chroma_db"
)

splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=150
    )


# Load_documents
class DocumentLoader:

    def __init__(self):
        self.supported_formats = {
            ".pdf": PyPDFLoader,
            ".docx": Docx2txtLoader,
            ".txt": TextLoader,
            ".csv": CSVLoader,
            ".xlsx": UnstructuredExcelLoader,
            ".pptx": UnstructuredPowerPointLoader,
        }

    def load_document(self, file_path: str):

        path = Path(file_path)

        print(path)

        if not path.exists():
            raise FileNotFoundError(
                f"File not found: {file_path}"
            )

        extension = path.suffix.lower()

        print(path.suffix)

        loader_class = self.supported_formats.get(
            extension
        )

        if loader_class is None:
            raise ValueError(
                f"Unsupported file format: {extension}"
            )

        loader = loader_class(str(path))

        documents = loader.load()

        return documents

    def load_directory(self, directory: str):

        directory_path = Path(directory)

        print(directory_path)

        if not directory_path.is_dir():
            raise NotADirectoryError(directory)

        all_documents = []

        for file_path in directory_path.rglob("*"):

            if not file_path.is_file():
                continue

            if file_path.suffix.lower() not in self.supported_formats:
                continue

            try:

                documents = self.load_document(
                    str(file_path)
                )

                all_documents.extend(documents)

                print(f"Loaded: {file_path.name}")

            except Exception as e:

                print(
                    f"Failed to load {file_path.name}: {e}"
                )

        return all_documents


def add_rag(file_path: str, query: str):
    loader = DocumentLoader()

    documents = loader.load_document(file_path)

    chunks = splitter.split_documents(documents)

    vectorstore.add_documents(chunks)

    docs = vectorstore.similarity_search(query=query, k=4)    

    if not docs:
        return "No relevant documents found"

    results = []

    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "uploaded_documents")
        results.append(
            f"[Source {i}: {source}]\n{doc.page_content}"
        )

    return "\n\n".join(results)  




    



    

