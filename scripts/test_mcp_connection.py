import asyncio
import sys
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server.server"],
    )

    print("Connecting to MCP server...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:

            await session.initialize()

            print("MCP connection successful!")

            result = await session.list_tools()

            print(f"\nDiscovered {len(result.tools)} tools:\n")

            for tool in result.tools:
                print(f"Tool: {tool.name}")
                print(f"Description: {tool.description}")
                print(
                    "Input schema:",
                    json.dumps(tool.input_schema, indent=2)
                )
                print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())