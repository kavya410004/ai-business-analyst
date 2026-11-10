import json
import logging
import sys

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .gemini_provider import GeminiProvider
from .models import AgentResponse, ToolExecution
from .prompts import SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 8


class AgentOrchestrator:

    def __init__(self):
        self.provider = GeminiProvider()

        self.server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_server.server"],
        )

    async def ask(self, question: str) -> AgentResponse:
        executions = []

        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:

                await session.initialize()

                mcp_response = await session.list_tools()
                available_tools = mcp_response.tools

                gemini_tools = self.provider.build_tools(
                    available_tools
                )

                contents = [
                    {
                        "role": "user",
                        "parts": [{"text": question}],
                    }
                ]
                executed_calls = set()
                for iteration in range(MAX_ITERATIONS):

                    response = self.provider.generate(
                        contents=contents,
                        system_instruction=SYSTEM_PROMPT,
                        tools=gemini_tools,
                    )

                    candidate = response.candidates[0]
                    contents.append(candidate.content)

                    function_calls = [
                        part.function_call
                        for part in candidate.content.parts
                        if part.function_call
                    ]

                    
                    if not function_calls:
                        return AgentResponse(
                            answer=response.text or
                            "I couldn't generate a response.",
                            tool_executions=executions,
                            model_used=self.provider.last_model_used,
                        )

                    for function_call in function_calls:

                        tool_name = function_call.name
                        arguments = dict(function_call.args or {})

                        logger.info(
                            "Executing MCP tool: %s",
                            tool_name,
                        )

                        call_signature = (
                            tool_name,
                            json.dumps(arguments, sort_keys=True, default=str),
                        )
                        if call_signature in executed_calls:
                            continue
                        executed_calls.add(call_signature)
                        
                        try:
                            result = await session.call_tool(
                                tool_name,
                                arguments=arguments,
                            )

                            if result.is_error:
                                tool_result = {
                                    "error": True,
                                    "details": [
                                        block.text
                                        for block in result.content
                                        if hasattr(block, "text")
                                    ],
                                }
                            else:
                                tool_result = self._parse_result(result)

                        except Exception as exc:
                            logger.exception(
                                "MCP tool execution failed: %s",
                                tool_name,
                            )

                            tool_result = {
                                "error": True,
                                "details": str(exc),
                            }

                        executions.append(
                            ToolExecution(
                                name=tool_name,
                                arguments=arguments,
                                result=tool_result,
                            )
                        )

                        contents.append(
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "function_response": {
                                            "name": tool_name,
                                            "response": {
                                                "result": tool_result
                                            },
                                        }
                                    }
                                ],
                            }
                        )

                return AgentResponse(
                    answer=(
                        "I couldn't complete the analysis within "
                        "the allowed tool-calling iterations. "
                        "Please narrow your question."
                    ),
                    tool_executions=executions,
                    model_used=self.provider.last_model_used,
                )

    @staticmethod
    def _parse_result(result):
        parsed = []

        for block in result.content:
            if hasattr(block, "text"):
                try:
                    parsed.append(json.loads(block.text))
                except (json.JSONDecodeError, TypeError):
                    parsed.append(block.text)

        if len(parsed) == 1:
            return parsed[0]

        return parsed