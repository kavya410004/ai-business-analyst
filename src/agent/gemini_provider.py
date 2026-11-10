import os
from typing import Any

from google import genai
from google.genai import types


class GeminiProvider:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("GEMINI_API_KEY is missing")

        self.client = genai.Client(api_key=api_key)

        self.primary_model = os.getenv(
            "GEMINI_PRIMARY_MODEL", "gemini-3.5-flash-lite"
        )
        self.fallback_model = os.getenv(
            "GEMINI_FALLBACK_MODEL", "gemini-3.8-flash"
        )

        self.last_model_used = self.primary_model

    @staticmethod
    def clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
        """Convert MCP JSON schema to the supported Gemini schema subset."""

        result = {}

        schema_type = schema.get("type")

        if schema_type in ("object", "string", "integer",
                           "number", "boolean", "array"):
            result["type"] = schema_type

        for key in ("description", "enum"):
            if key in schema:
                result[key] = schema[key]

        if "properties" in schema:
            result["properties"] = {
                name: GeminiProvider.clean_schema(value)
                for name, value in schema["properties"].items()
            }

        if "items" in schema:
            result["items"] = GeminiProvider.clean_schema(schema["items"])

        if "required" in schema:
            result["required"] = schema["required"]

        return result

    def build_tools(self, mcp_tools: list):
        declarations = []

        for tool in mcp_tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description or "",
                    parameters_json_schema=self.clean_schema(
                        tool.input_schema
                    ),
                )
            )

        return [types.Tool(function_declarations=declarations)]

    def generate(self, contents, system_instruction, tools):
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            temperature=0,
        )

        try:
            response = self.client.models.generate_content(
                model=self.primary_model,
                contents=contents,
                config=config,
            )
            self.last_model_used = self.primary_model
            return response

        except Exception as exc:
            status = (
                getattr(exc, "code", None)
                or getattr(exc, "status_code", None)
            )

            if status not in (429, 503):
                raise

            response = self.client.models.generate_content(
                model=self.fallback_model,
                contents=contents,
                config=config,
            )

            self.last_model_used = self.fallback_model
            return response