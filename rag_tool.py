
import os
import hashlib

from pathlib import Path
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.tools import tool, InjectedToolArg
from langchain_core.runnables import RunnableConfig
from langchain_text_splitters import RecursiveCharacterTextSplitter

from typing import Annotated

from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
    CSVLoader,
    UnstructuredExcelLoader,
    UnstructuredPowerPointLoader,
)


load_dotenv()


# ==========================================
# DIRECTORIES
# ==========================================

UPLOAD_DIR = Path("Uploads")
CHROMA_DIR = Path("Chroma_db")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# EMBEDDINGS
# ==========================================

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


# ==========================================
# CHROMA VECTOR DATABASE
# ==========================================

vectorstore = Chroma(
    collection_name="erp_chatbot_docs",
    embedding_function=embeddings,
    persist_directory=str(CHROMA_DIR)
)


# ==========================================
# TEXT SPLITTER
# ==========================================

splitter = RecursiveCharacterTextSplitter(
    chunk_size=900,
    chunk_overlap=150
)


# ==========================================
# DOCUMENT LOADER
# ==========================================

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

        if not path.exists():
            raise FileNotFoundError(
                f"File not found: {file_path}"
            )

        extension = path.suffix.lower()

        loader_class = self.supported_formats.get(extension)

        if loader_class is None:
            raise ValueError(
                f"Unsupported file format: {extension}"
            )

        loader = loader_class(str(path))

        return loader.load()

    def load_directory(self, directory: str):

        directory_path = Path(directory)

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

            except Exception as e:

                print(
                    f"Failed to load {file_path.name}: {e}"
                )

        return all_documents


# ==========================================
# RAG TOOL
# ==========================================

@tool
def add_rag(
    file_path: str,
    query: str,
    config: RunnableConfig
) -> str:
    """
    Load a document, index it into ChromaDB and retrieve
    relevant information.

    Documents are isolated by LangGraph thread ID.

    Args:
        file_path: Path to the uploaded document.
        query: Question or instruction about the document.

    Returns:
        Relevant document chunks for the current conversation.
    """

    # ======================================
    # GET CURRENT THREAD ID
    # ======================================

    thread_id = (
        config.get("configurable", {}).get("thread_id")
    )

    if not thread_id:
        raise ValueError(
            "Thread ID is missing from LangGraph configuration."
        )

    # ======================================
    # LOAD DOCUMENT
    # ======================================

    loader = DocumentLoader()

    documents = loader.load_document(file_path)

    if not documents:
        return "No content found in the uploaded document."

    # ======================================
    # SPLIT DOCUMENT
    # ======================================

    chunks = splitter.split_documents(documents)

    if not chunks:
        return "No document chunks were generated."

    # ======================================
    # ADD THREAD METADATA
    # ======================================

    source_path = str(Path(file_path).resolve())

    document_id = hashlib.sha256(
        f"{thread_id}:{source_path}".encode()
    ).hexdigest()

    for index, chunk in enumerate(chunks):

        chunk.metadata.update({
            "thread_id": thread_id,
            "document_id": document_id,
            "source": Path(file_path).name,
            "chunk_index": index
        })

    # ======================================
    # INDEX DOCUMENT
    # ======================================

    chunk_ids = [
        hashlib.sha256(
            f"{document_id}:{index}".encode()
        ).hexdigest()
        for index in range(len(chunks))
    ]

    vectorstore.add_documents(
        documents=chunks,
        ids=chunk_ids
    )

    # ======================================
    # THREAD-SPECIFIC RETRIEVAL
    # ======================================

    docs = vectorstore.similarity_search(
        query=query,
        k=4,
        filter={
            "thread_id": thread_id
        }
    )

    if not docs:
        return "No relevant documents found."

    # ======================================
    # FORMAT RESULTS
    # ======================================

    results = []

    for index, doc in enumerate(docs, start=1):

        source = doc.metadata.get(
            "source",
            "uploaded_documents"
        )

        results.append(
            f"[Source {index}: {source}]\n"
            f"{doc.page_content}"
        )

    return "\n\n".join(results)
