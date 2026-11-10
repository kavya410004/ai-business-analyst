from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolExecution:
    name: str
    arguments: dict[str, Any]
    result: Any


@dataclass
class AgentResponse:
    answer: str
    tool_executions: list[ToolExecution] = field(default_factory=list)
    model_used: str | None = None