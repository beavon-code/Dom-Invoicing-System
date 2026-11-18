
import os
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

CAVE_API_KEY = os.getenv("CAVE_API_KEY")

if not CAVE_API_KEY:
    raise ValueError("CAVE_API_KEY is missing from your .env file.")

client = MultiServerMCPClient(
    {
        "invoicecave": {
            "transport": "streamable_http",
            "url": "https://www.invoicecave.com/api/mcp/mcp",
            "headers": {
                "Authorization": f"Bearer {CAVE_API_KEY}",
            },
        },
    }
)


async def get_invoice_tools():
    
    tools = await client.get_tools()

    
    tools_by_name = {
        tool.name: tool
        for tool in tools
    }

    required_tools = [
        "create_credit_note",
        "create_invoice",
        "create_quote",
    ]

    missing_tools = [
        name
        for name in required_tools
        if name not in tools_by_name
    ]

    if missing_tools:
        raise RuntimeError(
            f"Missing MCP tools: {missing_tools}. "
        )

    print("MCP tools loaded successfully:")

    return {
        "credit_tool": tools_by_name["create_credit_note"],
        "invoice_tool": tools_by_name["create_invoice"],
        "quote_tool": tools_by_name["create_quote"],
    }



