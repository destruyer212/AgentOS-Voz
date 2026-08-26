"""Motor de workflows minimo (Sprint 5 del roadmap).

Ejecuta una definicion de pasos (`WorkflowDefinition`) contra un contexto
mutable, llamando tools autorizadas para los pasos de tipo "tool" y
evaluando condiciones simples por path para los de tipo "condition". Se
detiene en el primer fallo y siempre devuelve una traza completa apta para
auditoria (persistida por quien lo invoca).
"""

from __future__ import annotations

from typing import Any

from app.tools.registry import ToolRegistry
from app.workflows.models import StepTrace, WorkflowDefinition, WorkflowRunResult


def _resolve_path(context: dict[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
        if value is None:
            return None
    return value


class WorkflowEngine:
    def __init__(self, tools: ToolRegistry):
        self.tools = tools

    async def run(self, definition: WorkflowDefinition, context: dict[str, Any]) -> WorkflowRunResult:
        trace: list[StepTrace] = []

        for step in definition.steps:
            if step.type == "end":
                trace.append(StepTrace(key=step.key, type="end", status="ok"))
                break

            if step.type == "condition":
                value = _resolve_path(context, step.check_path or "")
                if not value:
                    message = step.fail_message or f"Condicion no cumplida: {step.check_path}"
                    trace.append(StepTrace(key=step.key, type="condition", status="failed", detail=message))
                    return WorkflowRunResult(definition.key, "failed", context, trace, message)
                trace.append(StepTrace(key=step.key, type="condition", status="ok"))
                continue

            if step.type == "tool":
                arguments = {name: _resolve_path(context, path) for name, path in step.input_map.items()}
                try:
                    assert step.tool, f"Paso {step.key} de tipo tool sin nombre de tool"
                    result = await self.tools.call(step.tool, arguments)
                except Exception as exc:  # DomainError u otros fallos de negocio/infra
                    trace.append(
                        StepTrace(
                            key=step.key,
                            type="tool",
                            status="failed",
                            tool=step.tool,
                            arguments=arguments,
                            detail=str(exc),
                        )
                    )
                    return WorkflowRunResult(definition.key, "failed", context, trace, str(exc))

                if step.output_key:
                    context[step.output_key] = result
                trace.append(
                    StepTrace(
                        key=step.key,
                        type="tool",
                        status="ok",
                        tool=step.tool,
                        arguments=arguments,
                        result=result,
                    )
                )
                continue

        return WorkflowRunResult(definition.key, "completed", context, trace, None)
