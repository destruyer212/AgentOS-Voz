from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StepType = Literal["tool", "condition", "end"]


@dataclass
class WorkflowStep:
    key: str
    type: StepType
    tool: str | None = None
    input_map: dict[str, str] = field(default_factory=dict)
    output_key: str | None = None
    check_path: str | None = None
    fail_message: str | None = None


@dataclass
class WorkflowDefinition:
    key: str
    name: str
    steps: list[WorkflowStep]


@dataclass
class StepTrace:
    key: str
    type: str
    status: str
    detail: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


@dataclass
class WorkflowRunResult:
    workflow_key: str
    status: str
    context: dict[str, Any]
    trace: list[StepTrace]
    error: str | None = None
