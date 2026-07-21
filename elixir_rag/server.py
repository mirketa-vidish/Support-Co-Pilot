import logging
import sys

from mcp.server.fastmcp import FastMCP

from . import tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("elixir_rag.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)

mcp = FastMCP("elixir-support-rag")

list_projects = mcp.tool()(tools.list_projects)
list_cases = mcp.tool()(tools.list_cases)
search_documents = mcp.tool()(tools.search_documents)
extract_log_signals = mcp.tool()(tools.extract_log_signals)
list_code_files = mcp.tool()(tools.list_code_files)
get_file_content = mcp.tool()(tools.get_file_content)


if __name__ == "__main__":
    logging.getLogger("elixir_rag.server").info("Starting Elixir Support RAG MCP server")
    mcp.run()
