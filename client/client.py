import asyncio
import sys
import json
import os
import logging
from typing import Optional, Dict, Any, List
from contextlib import AsyncExitStack
from dotenv import load_dotenv, find_dotenv
import traceback
import colorama
import google.generativeai as genai
from mcp import ClientSession
from mcp.client.sse import sse_client

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
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.is_connected = False

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
        self.client = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
        logger.info(f"Gemini client initialized with model: {os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}")

        self.available_tools = []

    async def connect_to_server(self) -> bool:
        try:
            server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")
            logger.info(f"Connecting to MCP server via SSE at: {server_url}")
            recv, send = await self.exit_stack.enter_async_context(sse_client(server_url))
            self.session = await self.exit_stack.enter_async_context(ClientSession(recv, send))
            await self.session.initialize()
            await self.refresh_available_tools()
            self.is_connected = True
            return True
        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to server: {str(e)}")
            logger.debug(traceback.format_exc())
            return False

    async def refresh_available_tools(self) -> List[Dict[str, Any]]:
        if not self.session:
            raise ConnectionError("Not connected to a server.")
        try:
            logger.info("Refreshing available tools from MCP server")
            response = await self.session.list_tools()
            self.available_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                }
                for tool in response.tools
            ]
            return self.available_tools
        except Exception as e:
            logger.error(f"Failed to refresh tools: {str(e)}")
            logger.debug(traceback.format_exc())
            return []

    async def refresh_available_resources(self) -> List[str]:
        if not self.session:
            raise ConnectionError("Not connected to a server.")
        try:
            logger.info("Refreshing available resources from MCP server")
            response = await self.session.list_resources()
            return [r.uri for r in response.resources]
        except Exception as e:
            logger.error(f"Failed to fetch resources: {str(e)}")
            logger.debug(traceback.format_exc())
            return []

    async def process_query(self, query: str) -> str:
        if not self.is_connected or not self.session:
            raise ConnectionError("Not connected to a server. Call connect_to_server() first.")

        logger.info(f"Processing query: {query}")

        try:
            if not self.available_tools:
                await self.refresh_available_tools()
            resources = await self.refresh_available_resources()

            tool_descriptions = "\n".join([
                f'- {tool["function"]["name"]}({", ".join([f"{k}: {v}" for k, v in tool["function"]["parameters"]["properties"].items()])})'
                for tool in self.available_tools
            ])
            resource_descriptions = "\n".join(
                f'- "{uri}" (use with resolve_resource(uri="{uri}"))' for uri in resources
            )

            prompt = f"""
You are a helpful assistant with access to the following tools:

{tool_descriptions}

You also have access to the following resources:
{resource_descriptions}

To retrieve a resource, use the `resolve_resource` tool with a URI like so:
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
            response = self.client.generate_content(prompt)
            raw_response = response.text
            logger.info(f"Gemini raw response: {raw_response}")

            # Clean up markdown-style code blocks
            if raw_response.startswith("```"):
                raw_response = raw_response.strip().strip("`")
                if raw_response.lower().startswith("json"):
                    raw_response = raw_response[len("json"):].strip()

            logger.info(f"Sanitized Gemini response: {raw_response}")
            tool_call = json.loads(raw_response)
            final_text = []

            if tool_call.get("tool"):
                tool_name = tool_call["tool"]
                tool_args = tool_call.get("args", {})

                logger.info(f"Executing tool call: {tool_name} with args: {tool_args}")
                final_text.append(f"\n{colorama.Fore.BLUE}[Executing {tool_name}]{colorama.Style.RESET_ALL}")

                try:
                    result = await self.session.call_tool(tool_name, tool_args)
                    tool_result = result.content[0].text if result.content else "No results returned from tool."
                    logger.debug(f"Tool {tool_name} returned: {tool_result[:100]}...")
                    final_text.append(f"{colorama.Fore.CYAN}[Result]{colorama.Style.RESET_ALL}")
                    final_text.append(f"{tool_result}\n")
                    return "\n".join(final_text)
                except Exception as e:
                    error_msg = f"Error executing tool {tool_name}: {str(e)}"
                    logger.error(error_msg)
                    final_text.append(f"{colorama.Fore.RED}[Error]{colorama.Style.RESET_ALL} {error_msg}")
                    return "\n".join(final_text)
            else:
                answer = tool_call.get("answer", "No answer provided.")
                logger.info("Returning direct response")
                return answer

        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in Gemini response: {str(e)}"
            logger.error(error_msg)
            return f"{colorama.Fore.RED}Error:{colorama.Style.RESET_ALL} {error_msg}"
        except Exception as e:
            error_msg = f"Failed to process query: {str(e)}"
            logger.error(error_msg)
            logger.debug(traceback.format_exc())
            return f"{colorama.Fore.RED}Error:{colorama.Style.RESET_ALL} {error_msg}"

    async def chat_loop(self):
        print(f"\n{colorama.Fore.GREEN}=== Redshift Database Client with Gemini ==={colorama.Style.RESET_ALL}")
        print(f"{colorama.Fore.CYAN}Model: {os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')} | Server: {os.getenv('MCP_SERVER_URL')}{colorama.Style.RESET_ALL}")
        print(f"{colorama.Fore.CYAN}Type your database queries or questions. Type 'help' for commands or 'quit' to exit.{colorama.Style.RESET_ALL}")

        commands = {
            "help": "Show available commands",
            "quit": "Exit the application",
            "tools": "List available tools",
            "reconnect": "Reconnect to the server"
        }

        print(f"\n{colorama.Fore.YELLOW}Connecting to Redshift server...{colorama.Style.RESET_ALL}")
        if await self.connect_to_server():
            print(f"{colorama.Fore.GREEN}Connected successfully!{colorama.Style.RESET_ALL}")
        else:
            print(f"{colorama.Fore.RED}Failed to connect to server. Use 'reconnect' command.{colorama.Style.RESET_ALL}")

        while True:
            try:
                query = input(f"\n{colorama.Fore.YELLOW}Query>{colorama.Style.RESET_ALL} ").strip()
                if not query:
                    continue
                if query.lower() == 'quit':
                    print(f"{colorama.Fore.GREEN}Goodbye!{colorama.Style.RESET_ALL}")
                    break
                elif query.lower() == 'help':
                    print(f"\n{colorama.Fore.CYAN}Available commands:{colorama.Style.RESET_ALL}")
                    for cmd, desc in commands.items():
                        print(f"  {colorama.Fore.GREEN}{cmd}{colorama.Style.RESET_ALL}: {desc}")
                    continue
                elif query.lower() == 'tools':
                    if not self.is_connected:
                        print(f"{colorama.Fore.RED}Not connected to server. Use 'reconnect' first.{colorama.Style.RESET_ALL}")
                        continue
                    await self.refresh_available_tools()
                    print(f"\n{colorama.Fore.CYAN}Available tools:{colorama.Style.RESET_ALL}")
                    for tool in self.available_tools:
                        print(f"  {colorama.Fore.GREEN}{tool['function']['name']}{colorama.Style.RESET_ALL}: {tool['function']['description']}")
                    continue
                elif query.lower() == 'reconnect':
                    print(f"{colorama.Fore.CYAN}Reconnecting to server...{colorama.Style.RESET_ALL}")
                    if await self.connect_to_server():
                        print(f"{colorama.Fore.GREEN}Successfully reconnected!{colorama.Style.RESET_ALL}")
                    else:
                        print(f"{colorama.Fore.RED}Reconnection failed. Check logs for details.{colorama.Style.RESET_ALL}")
                    continue
                if not self.is_connected:
                    print(f"{colorama.Fore.RED}Not connected to server. Use 'reconnect' first.{colorama.Style.RESET_ALL}")
                    continue
                print(f"{colorama.Fore.CYAN}Processing your query...{colorama.Style.RESET_ALL}")
                response = await self.process_query(query)
                print(response)
            except KeyboardInterrupt:
                print(f"\n{colorama.Fore.YELLOW}Operation cancelled. Type 'quit' to exit.{colorama.Style.RESET_ALL}")
                continue
            except Exception as e:
                logger.error(f"Error in chat loop: {str(e)}")
                print(f"\n{colorama.Fore.RED}Error:{colorama.Style.RESET_ALL} {str(e)}")

    async def cleanup(self):
        logger.info("Cleaning up resources")
        try:
            await self.exit_stack.aclose()
            self.is_connected = False
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

async def main():
    client = None
    try:
        client = MCPClient()
        await client.chat_loop()
    except KeyboardInterrupt:
        print(f"\n{colorama.Fore.YELLOW}Application terminated by user.{colorama.Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{colorama.Fore.RED}Fatal error: {str(e)}{colorama.Style.RESET_ALL}")
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
    finally:
        if client and hasattr(client, 'exit_stack'):
            await client.exit_stack.aclose()
        print(f"\n{colorama.Fore.CYAN}Thank you for using Redshift Database Client!{colorama.Style.RESET_ALL}")

if __name__ == "__main__":
    asyncio.run(main())
