

import os

import uuid

import sqlite3

import operator

import threading



from pathlib import Path

from datetime import datetime, timezone

from contextlib import asynccontextmanager

from typing import TypedDict, Annotated, Optional, Any



from dotenv import load_dotenv



from fastapi import FastAPI, HTTPException, UploadFile, File, Request

from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field



from langgraph.graph import StateGraph, START

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from langgraph.prebuilt import ToolNode, tools_condition



from langchain_core.messages import (

    AnyMessage,

    HumanMessage,

    SystemMessage,

)



from langchain_deepseek import ChatDeepSeek

from mcp_client import get_invoice_tools

from rag_tool import add_rag

from fastapi.staticfiles import StaticFiles

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from fastapi.templating import Jinja2Templates





# ============================================================

# PATHS AND ENVIRONMENT VARIABLES

# ============================================================



BASE_DIR = Path(__file__).resolve().parent



UPLOAD_DIR = BASE_DIR / "Uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)



load_dotenv(BASE_DIR / ".env")



DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")



if not DEEPSEEK_API_KEY:

    raise ValueError(

        "DEEPSEEK_API_KEY is missing. "

        "Add it to your .env file."

    )



# Keep the database in the project directory.

DB_PATH = BASE_DIR / "sqlite.db"
CHECKPOINT_DB_PATH = BASE_DIR / "checkpoints.sqlite"





# ============================================================

# SYSTEM PROMPT

# ============================================================



system_message = """

You are the **Dom-Invoicing AI Agent**, an expert accounting assistant for DOMSHON EAST AFRICA LIMITED.

Your primary function is to analyze uploaded documents (like Purchase Orders), extract data accurately, and generate Invoices, Quotes, or Credit Notes using the tools provided to you.



### CORE RESPONSIBILITIES

1. Analyze the provided document text (OCR).

2. Extract key entities (Vendor, Customer, PO Number, Dates, Items, Quantities, Prices, Taxes).

3. Generate the requested document (Invoice, Quote, or Credit Note) using the provided tools.

4. Answer user queries based strictly on the uploaded document and generated outputs.



### DOCUMENT EXTRACTION RULES

When reading a document, extract the following data:

- **Customer Details:** Name, Address, VAT/Reg No.

- **Document Details:** PO Number, Date, Payment Terms, Currency.

- **Line Items:** Item Code, Description, Quantity, UOM (Unit of Measure), Unit Price, VAT Rate.

- **Totals:** Subtotal, VAT Amount, Total Amount.



⚠️ **CRITICAL VERIFICATION RULE (SIZE/DESCRIPTION MISMATCHES):**

Pay close attention to "Comments/Special Instructions" versus the "Item Description".

*Example from a document:* The comments say "SIZE 6=3, SIZE 7=1, SIZE 8=9, SIZE 10=3" (Total 16). The Item description says "Size 6-3, Size 7-1, Size 8-9, Size 9-3" (Total 16).

*Action:* You must use the **Total Quantity** listed in the QTY column (e.g., 16 PAA). In the generated document's line item description, you must accurately reflect the sizes. If there is a conflict between the header comments and the item description, prioritize the Item Description but flag the discrepancy in your text response to the user.



### INVOICING RULES (KENYA CONTEXT)

- **Currency:** Ensure the correct currency is used (typically KES).

- **Tax (VAT):** Standard VAT rate in Kenya is 16%. Unless specified otherwise, calculate VAT on top of the unit price (Subtotal * 1.16 = Total).

- **Validity:** Quotes are typically valid for 30 days unless specified otherwise.

- **Dates:** Use standard ISO format (YYYY-MM-DD) or local format (DD.MM.YYYY) matching the source document.



### TOOL USAGE INSTRUCTIONS

You have access to tools for creating Invoices, Quotes, and Credit Notes.

- Do NOT hallucinate tool names. Only use the tools explicitly provided.

- Before calling a tool, ensure you have all mandatory fields (Customer Name, Line Items, Total Amount).

- If the user asks for an Invoice, use the Invoice tool. If they ask for a Quote, use the Quote tool.

- If the user asks to generate a Credit Note, reverse the quantities or amounts appropriately and use the Credit Note tool.



### RESPONSE FORMATTING

When responding to the user:

1. **Acknowledge the Document:** Briefly state what document was uploaded (e.g., "I have analyzed Purchase Order 4100083004 from Mabati Rolling Mills Ltd.").

2. **Execution Summary:** State what tool you used and confirm successful generation (e.g., "I have successfully generated Invoice #INV-2026-001 using the Invoice tool.").

3. **Data Verification:** Present a clean markdown table of the extracted items and totals so the user can verify the data before finalizing.

4. **Answer Queries:** If the user asked a question (e.g., "What is the total VAT?"), answer it directly using the extracted data.



### EXAMPLE WORKFLOW

**User:** "Uploads PO 4100083004. Please generate an invoice for this."

**Agent Thought:** I need to extract the data from PO 4100083004. Customer is MRM. Items are Goliath Shoes, Qty 16, Unit Price 10,000, VAT 16%. Total is 185,600. I will call the Invoice tool.

**Agent Action:** [Calls Invoice Tool with extracted JSON data]

**Agent Response:**

"I have analyzed PO 4100083004 from Mabati Rolling Mills Ltd. and successfully generated the corresponding Invoice.

Here is the summary:

| Description | Qty | Unit Price | VAT | Total |

| :--- | :--- | :--- | :--- | :--- |

| Goliath Shoes (Mixed Sizes) | 16 | 10,000.00 | 16% | 185,600.00 |



*Note: The PO comments and item description had a slight mismatch regarding Size 9/10, but the total quantity of 16 was consistent and used.*"

"""



SYSTEM_PROMPT = SystemMessage(content=system_message)





# ============================================================

# DATABASE CONNECTION AND LOCK

# ============================================================





conn = sqlite3.connect(

    database=str(DB_PATH),

    check_same_thread=False,

    timeout=30

)



db_lock = threading.RLock()








# ============================================================

# THREAD DATABASE

# ============================================================



def initialize_thread_database():

    """Create the threads table if it does not exist."""



    with db_lock:

        conn.execute(

            """

            CREATE TABLE IF NOT EXISTS threads (

                thread_id TEXT PRIMARY KEY,

                title TEXT NOT NULL,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL

            )

            """

        )



        conn.commit()





def create_thread(title: str = "New Conversation") -> str:

    """Create a new conversation thread."""



    thread_id = str(uuid.uuid4())

    now = datetime.now(timezone.utc).isoformat()



    with db_lock:

        conn.execute(

            """

            INSERT INTO threads (

                thread_id,

                title,

                created_at,

                updated_at

            )

            VALUES (?, ?, ?, ?)

            """,

            (thread_id, title, now, now)

        )



        conn.commit()



    return thread_id





def get_all_threads():

    """Return all conversation threads."""



    with db_lock:

        cursor = conn.execute(

            """

            SELECT

                thread_id,

                title,

                created_at,

                updated_at

            FROM threads

            ORDER BY updated_at DESC

            """

        )



        rows = cursor.fetchall()



    return [

        {

            "thread_id": row[0],

            "title": row[1],

            "created_at": row[2],

            "updated_at": row[3]

        }

        for row in rows

    ]





def get_thread(thread_id: str):

    """Retrieve one conversation thread."""



    with db_lock:

        cursor = conn.execute(

            """

            SELECT

                thread_id,

                title,

                created_at,

                updated_at

            FROM threads

            WHERE thread_id = ?

            """,

            (thread_id,)

        )



        row = cursor.fetchone()



    if row is None:

        return None



    return {

        "thread_id": row[0],

        "title": row[1],

        "created_at": row[2],

        "updated_at": row[3]

    }





def update_thread(thread_id: str, title: Optional[str] = None):

    """Update a thread's title and last activity time."""



    now = datetime.now(timezone.utc).isoformat()



    with db_lock:



        if title:

            conn.execute(

                """

                UPDATE threads

                SET title = ?, updated_at = ?

                WHERE thread_id = ?

                """,

                (title, now, thread_id)

            )



        else:

            conn.execute(

                """

                UPDATE threads

                SET updated_at = ?

                WHERE thread_id = ?

                """,

                (now, thread_id)

            )



        conn.commit()





# ============================================================

# LANGGRAPH STATE

# ============================================================



class ERPState(TypedDict):

    messages: Annotated[list[AnyMessage], operator.add]





# ============================================================

# DEEPSEEK MODEL

# ============================================================



llm = ChatDeepSeek(

    model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),

    temperature=0.7,

    api_key=DEEPSEEK_API_KEY

)





# ============================================================

# BUILD LANGGRAPH WORKFLOW

# ============================================================



def build_workflow(tools, checkpointer):

    if not tools:

        raise RuntimeError("No tools were provided to LangGraph.")



    # Bind tools to DeepSeek.

    llm_with_tools = llm.bind_tools(tools)



    # LangGraph tool execution node.

    tool_node = ToolNode(tools)



    # --------------------------------------------------------

    # CHAT NODE

    # --------------------------------------------------------



    async def chat_node(state: ERPState):



        messages = state["messages"]



        response = await llm_with_tools.ainvoke(

            [

                SYSTEM_PROMPT,

                *messages

            ]

        )



        return {

            "messages": [response]

        }



    # --------------------------------------------------------

    # GRAPH

    # --------------------------------------------------------



    graph = StateGraph(ERPState)



    graph.add_node("chat_node", chat_node)



    graph.add_node("tools", tool_node)



    graph.add_edge(

        START,

        "chat_node"

    )



    graph.add_conditional_edges(

        "chat_node",

        tools_condition

    )



    graph.add_edge(

        "tools",

        "chat_node"

    )



    workflow = graph.compile(

        checkpointer=checkpointer

    )



    return workflow





# ============================================================

# PYDANTIC REQUEST MODELS

# ============================================================



class ChatRequest(BaseModel):



    message: str = Field(

        ...,

        min_length=1,

        description="Message sent to the invoicing agent."

    )



    thread_id: Optional[str] = None





class ThreadRequest(BaseModel):



    title: str = Field(

        default="New Conversation",

        max_length=150

    )





class UpdateThreadRequest(BaseModel):



    title: str = Field(

        ...,

        min_length=1,

        max_length=150

    )





# ============================================================

# MESSAGE SERIALIZATION

# ============================================================



def serialize_messages(messages):

    """Convert LangChain messages into JSON-friendly objects."""



    serialized = []



    for message in messages:



        serialized.append(

            {

                "role": message.type,

                "content": message.content

            }

        )



    return serialized





# ============================================================

# FASTAPI LIFESPAN

# ============================================================



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize metadata storage, MCP tools and async LangGraph."""
    print("\nStarting Dom Invoicing AI Agent...")

    initialize_thread_database()

    try:
        print("\nConnecting to InvoiceCave MCP...")
        mcp_tools = await get_invoice_tools()

        required_tools = ("credit_tool", "quote_tool", "invoice_tool")
        missing = [name for name in required_tools if name not in mcp_tools]
        if missing:
            raise RuntimeError(f"MCP tools missing: {', '.join(missing)}")

        tools = [
            mcp_tools["credit_tool"],
            mcp_tools["quote_tool"],
            mcp_tools["invoice_tool"],
            add_rag,
        ]

        async with AsyncSqliteSaver.from_conn_string(
            str(CHECKPOINT_DB_PATH)
        ) as checkpointer:
            await checkpointer.setup()
            app.state.workflow = build_workflow(tools, checkpointer)
            print("\nDom Invoicing AI Agent is ready.")
            yield

    finally:
        print("\nShutting down Dom Invoicing AI Agent.")
        with db_lock:
            conn.close()
# ============================================================

# FASTAPI APPLICATION

# ============================================================



app = FastAPI(

    title="Dom Invoicing AI Agent",

    description=(

        "AI-powered invoicing assistant using "

        "LangGraph, DeepSeek, MCP and RAG."

    ),

    version="1.0.0",

    lifespan=lifespan

)





# ============================================================

# CORS

# ============================================================



# For development, these are common local frontend origins.

# Add your deployed frontend domain before production use.



app.add_middleware(

    CORSMiddleware,

    allow_origins=[

        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5500",
        "http://127.0.0.1:5500"

    ],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"]

)





# ============================================================

# HOME ENDPOINT

# ============================================================



@app.get("/", response_class=HTMLResponse)

async def home(request: Request):

    template_path = BASE_DIR / "templates" / "index.html"



    print("BASE DIRECTORY:", BASE_DIR)

    print("TEMPLATE EXISTS:", template_path.exists())

    print("TEMPLATE PATH:", template_path)



    return templates.TemplateResponse(

        request=request,

        name="index.html",

        context={}

    )



# ============================================================

# CREATE NEW THREAD

# ============================================================



@app.post("/threads")

def new_thread(request: ThreadRequest):



    thread_id = create_thread(

        title=request.title

    )



    return {

        "success": True,

        "thread_id": thread_id,

        "title": request.title

    }





# ============================================================

# GET ALL THREADS

# ============================================================



@app.get("/threads")

def list_threads():



    threads = get_all_threads()



    return {

        "success": True,

        "total": len(threads),

        "threads": threads

    }





# ============================================================

# UPDATE THREAD TITLE

# ============================================================



@app.patch("/threads/{thread_id}")

def rename_thread(

    thread_id: str,

    request: UpdateThreadRequest

):



    thread = get_thread(thread_id)



    if not thread:

        raise HTTPException(

            status_code=404,

            detail="Thread not found."

        )



    update_thread(

        thread_id=thread_id,

        title=request.title

    )



    return {

        "success": True,

        "thread_id": thread_id,

        "title": request.title

    }





# ============================================================

# CHAT ENDPOINT

# ============================================================



@app.post("/chat")
async def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    workflow = getattr(app.state, "workflow", None)
    if workflow is None:
        raise HTTPException(status_code=503, detail="The AI agent has not been initialized.")

    thread_id = request.thread_id
    if not thread_id:
        thread_id = create_thread(title=message[:60])
    elif not get_thread(thread_id):
        raise HTTPException(status_code=404, detail="Thread not found.")

    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await workflow.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )
        messages = result.get("messages", [])
        last_message = messages[-1] if messages else None
        update_thread(thread_id)

        return {
            "success": True,
            "thread_id": thread_id,
            "response": last_message.content if last_message else "",
            "messages": serialize_messages(messages),
        }
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {str(exc)}",
        ) from exc
# ============================================================

# GET CONVERSATION HISTORY

# ============================================================



@app.get("/threads/{thread_id}")
async def get_conversation_history(thread_id: str):
    thread = get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")

    workflow = getattr(app.state, "workflow", None)
    if workflow is None:
        raise HTTPException(status_code=503, detail="The AI agent has not been initialized.")

    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await workflow.aget_state(config)
        messages = state.values.get("messages", [])
        return {
            "success": True,
            "thread": thread,
            "total_messages": len(messages),
            "messages": serialize_messages(messages),
        }
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Could not retrieve conversation: {str(exc)}",
        ) from exc


ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx"}

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  





@app.post("/upload")

async def upload_document(file: UploadFile = File(...)):

    original_name = Path(file.filename or "").name

    extension = Path(original_name).suffix.lower()



    if extension not in ALLOWED_UPLOAD_EXTENSIONS:

        raise HTTPException(

            status_code=400,

            detail="Unsupported file type. Upload a PDF or DOCX document."

        )



    if not original_name:

        raise HTTPException(status_code=400, detail="A filename is required.")



    # Read one byte beyond the limit to detect oversized files.

    content = await file.read(MAX_UPLOAD_SIZE + 1)

    if not content:

        raise HTTPException(status_code=400, detail="The uploaded file is empty.")



    if len(content) > MAX_UPLOAD_SIZE:

        raise HTTPException(

            status_code=413,

            detail="File is too large. Maximum upload size is 20 MB."

        )



    upload_id = str(uuid.uuid4())

    safe_filename = f"{upload_id}{extension}"

    destination = (UPLOAD_DIR / safe_filename).resolve()



    # Ensure the destination remains inside the Uploads directory.

    if UPLOAD_DIR.resolve() not in destination.parents:

        raise HTTPException(status_code=400, detail="Invalid upload path.")



    try:

        destination.write_bytes(content)

    except OSError as exc:

        raise HTTPException(

            status_code=500,

            detail=f"Could not save uploaded document: {exc}"

        )



    return {

        "success": True,

        "upload_id": upload_id,

        "file_name": original_name,

        "file_path": str(destination),

        "size": len(content),

        "content_type": file.content_type

    }    



app.mount(

    "/static",

    StaticFiles(directory=str(BASE_DIR / "static")),

    name="static"

)





templates = Jinja2Templates(

    directory=str(BASE_DIR / "templates")

)



# ============================================================

# RUN APPLICATION

# ============================================================



if __name__ == "__main__":



    import uvicorn



    uvicorn.run(

        "app:app",

        host="127.0.0.1",

        port=8000,

        reload=True

    )
