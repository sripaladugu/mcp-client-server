import asyncio
import sys
import json
import os
import logging
import traceback
import colorama
from dotenv import load_dotenv, find_dotenv
import google.generativeai as genai
from fastmcp import Client as MCPClientCore

colorama.init()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mcp_client.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MCPClient")

class MCPClient:
    def __init__(self):
        self.is_connected = False
        self.client = None
        self.available_tools = []

        env_path = find_dotenv()
        if env_path:
            logger.info(f"Loading environment variables from {env_path}")
            load_dotenv(env_path)
        else:
            logger.warning("No .env file found. Using existing environment variables.")

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("Missing required environment variable: GEMINI_API_KEY")

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
        logger.info(f"Gemini client initialized with model: {os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}")

    async def connect_to_server(self) -> bool:
        try:
            server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")
            logger.info(f"Connecting to MCP server at: {server_url}")
            self.client = MCPClientCore(server_url)
            await self.client.__aenter__()
            self.is_connected = True
            await self.refresh_available_tools()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to server: {str(e)}")
            logger.debug(traceback.format_exc())
            return False

    async def refresh_available_tools(self):
        try:
            tools = await self.client.list_tools()
            self.available_tools = tools
            logger.info(f"Loaded {len(tools)} tools from server")
        except Exception as e:
            logger.error(f"Failed to list tools: {str(e)}")
            logger.debug(traceback.format_exc())

    async def process_query(self, query: str):
        if not self.is_connected:
            raise RuntimeError("Client not connected")

        try:
            tool_descriptions = "\n".join([
                f'- {tool.name}({", ".join([f"{k}: {v}" for k, v in tool.model_json_schema().get("properties", {}).items()])})'
                for tool in self.available_tools
            ])

            prompt = f"""
You are a helpful assistant with access to the following tools:

{tool_descriptions}

When using the `resolve_resource` tool, the `uri` argument is required.
Valid URIs include:

  - redshift://tables
  - redshift://views
  - redshift://schemas

Example usage:
{{
  "tool": "resolve_resource",
  "args": {{
    "uri": "redshift://tables"
  }}
}}

When responding to a query, respond ONLY in JSON like this:
{{
  "tool": "tool_name",
  "args": {{
    "arg1": "value1",
    "arg2": "value2"
  }}
}}

If no tool is needed, respond with:
{{
  "tool": null,
  "answer": "Direct response goes here."
}}

User: {query}
""".strip()

            logger.info("Sending prompt to Gemini")
            response = self.model.generate_content(prompt)
            raw = response.text.strip()

            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()

            logger.info(f"Gemini raw response: {raw}")
            reply = json.loads(raw)

            if reply.get("tool"):
                tool_name = reply["tool"]
                args = reply.get("args", {})
                # Patch arg keys for common mismatches (e.g. 'name' vs 'table_name')
                if tool_name == "get_table_schema" and "table_name" not in args and "name" in args:
                    args["table_name"] = args.pop("name")
                if tool_name == "query" and "sql" not in args and "query" in args:
                    args["sql"] = args.pop("query")
                    args["table_name"] = args.pop("name")
                result = await self.client.call_tool(tool_name, args)
                if hasattr(result, "text"):
                    result = result.text
                elif hasattr(result, "__str__"):
                    result = str(result)
                return f"[Executed {tool_name}]:{result}"
            else:
                return reply.get("answer", "No answer provided.")

        except json.JSONDecodeError as e:
            return f"Invalid JSON in Gemini response: {e}"
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}")
            logger.debug(traceback.format_exc())
            return f"Error: {e}"

    async def chat_loop(self):
        print(f"\n{colorama.Fore.GREEN}=== Redshift Database Client with Gemini ==={colorama.Style.RESET_ALL}")
        print(f"{colorama.Fore.CYAN}Model: {os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')} | Server: {os.getenv('MCP_SERVER_URL')}{colorama.Style.RESET_ALL}")

        print(f"\n{colorama.Fore.YELLOW}Connecting to Redshift server...{colorama.Style.RESET_ALL}")
        if await self.connect_to_server():
            print(f"{colorama.Fore.GREEN}Connected successfully!{colorama.Style.RESET_ALL}")
        else:
            print(f"{colorama.Fore.RED}Failed to connect. Use 'reconnect' command.{colorama.Style.RESET_ALL}")

        while True:
            try:
                query = input(f"\n{colorama.Fore.YELLOW}Query>{colorama.Style.RESET_ALL} ").strip()
                if query.lower() in ('quit', 'exit'):
                    print(f"{colorama.Fore.GREEN}Goodbye!{colorama.Style.RESET_ALL}")
                    break
                elif query.lower() == 'tools':
                    for tool in self.available_tools:
                        print(f"- {tool.name}: {tool.description}")
                    continue
                elif query.lower() == 'reconnect':
                    await self.client.__aexit__(None, None, None)
                    if await self.connect_to_server():
                        print("Reconnected successfully.")
                    else:
                        print("Reconnection failed.")
                    continue

                response = await self.process_query(query)
                print(response)
            except KeyboardInterrupt:
                print("Interrupted. Type 'quit' to exit.")
            except Exception as e:
                print(f"{colorama.Fore.RED}Error:{colorama.Style.RESET_ALL} {e}")

    async def cleanup(self):
        if self.client:
            await self.client.__aexit__(None, None, None)
        logger.info("Cleanup completed")

async def main():
    client = MCPClient()
    try:
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
