"""Provider-neutral parsing for Pi/agent JSON and JSONL traces.

This module only reports fields present in a trace.  It intentionally does not
guess token counts or turn boundaries when the provider did not expose them.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass
class RequestTelemetry:
    ordinal: int
    request_start: str | None = None
    request_end: str | None = None
    model: str | None = None
    provider: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    ttft_seconds: float | None = None
    wall_seconds: float | None = None
    stop_reason: str | None = None
    tool_calls: int = 0
    tool_names: list[str] = None  # type: ignore[assignment]
    invalid_tool_schema: int = 0
    invalid_argument_type: int = 0
    tool_errors: int = 0
    recovered_after_tool_error: bool | None = None
    alternate_tool_used: bool = False
    final_answer: str | None = None

    def __post_init__(self) -> None:
        if self.tool_names is None:
            self.tool_names = []

    def json(self) -> dict[str, Any]:
        return asdict(self)


def _objects(text: str | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(text, str):
        return [x for x in text if isinstance(x, dict)]
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    result = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


def _number(obj: dict[str, Any], *keys: str) -> int | float | None:
    value = _first(obj, *keys)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text_from_message(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return _text_from_message(message.get("content"))
    if isinstance(message, list):
        parts = []
        for item in message:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                parts.append(str(item.get("text", item.get("content", ""))))
        return "".join(parts)
    return ""


def parse_trace(trace: str | Iterable[dict[str, Any]]) -> list[RequestTelemetry]:
    """Parse common OpenAI/Anthropic/Pi event shapes into request records."""
    events = _objects(trace)
    requests: list[RequestTelemetry] = []
    current: RequestTelemetry | None = None
    last_text = ""
    tool_error_seen = False
    for event in events:
        nested = list(_walk(event))
        response = next((x for x in nested if isinstance(x.get("usage"), dict)), event)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        role = str(_first(event, "role", "type", "event") or "").lower()
        is_request = any(k in event for k in ("responseId", "response_id", "request_id", "requestId")) and (
            role in {"assistant", "message", "response", "model"} or "usage" in event or "message" in event
        )
        if current is None or is_request and (event.get("responseId") or event.get("response_id")) not in {None, "", getattr(current, "_response_id", None)}:
            if current is not None:
                current.recovered_after_tool_error = tool_error_seen and current.tool_errors == 0
                current.final_answer = last_text or None
                requests.append(current)
            current = RequestTelemetry(len(requests) + 1)
            response_id = _first(event, "responseId", "response_id", "request_id", "requestId")
            setattr(current, "_response_id", response_id)
            tool_error_seen = False
            last_text = ""
        if current is None:
            continue
        current.model = current.model or _first(event, "model", "model_name", "resolved_model")
        current.provider = current.provider or _first(event, "provider", "api", "transport")
        current.request_start = current.request_start or _first(event, "request_start", "started_at", "startTime", "timestamp")
        current.request_end = _first(event, "request_end", "ended_at", "endTime", "timestamp") or current.request_end
        current.input_tokens = current.input_tokens if current.input_tokens is not None else _number(usage, "prompt_tokens", "input_tokens")
        current.output_tokens = current.output_tokens if current.output_tokens is not None else _number(usage, "completion_tokens", "output_tokens")
        if current.reasoning_tokens is None:
            current.reasoning_tokens = _number(usage, "reasoning_tokens", "thinking_tokens")
            details = usage.get("completion_tokens_details")
            if current.reasoning_tokens is None and isinstance(details, dict):
                current.reasoning_tokens = _number(details, "reasoning_tokens")
        current.cache_read_tokens = current.cache_read_tokens if current.cache_read_tokens is not None else _number(usage, "cache_read_input_tokens", "cache_read_tokens", "cacheRead")
        current.cache_write_tokens = current.cache_write_tokens if current.cache_write_tokens is not None else _number(usage, "cache_creation_input_tokens", "cache_write_tokens", "cacheWrite")
        wall = _number(event, "wall_seconds", "duration_seconds")
        current.wall_seconds = float(wall) if wall is not None else current.wall_seconds
        stop = _first(event, "stop_reason", "stopReason", "finish_reason", "finishReason")
        current.stop_reason = stop or current.stop_reason
        visible = _text_from_message(event.get("message", event.get("content", event.get("output"))))
        if visible:
            last_text += visible
            if current.ttft_seconds is None:
                ttft = _number(event, "ttft_seconds", "first_token_seconds")
                current.ttft_seconds = float(ttft) if ttft is not None else current.ttft_seconds
        for child in nested:
            tool = child.get("toolCall", child.get("tool_call", child.get("function")))
            if isinstance(tool, dict):
                current.tool_calls += 1
                name = _first(tool, "name") or _first(child, "name")
                if isinstance(name, str) and name not in current.tool_names:
                    current.tool_names.append(name)
                if child.get("error") or child.get("isError") or str(child.get("type", "")).lower() in {"tool_error", "toolresult_error"}:
                    current.tool_errors += 1; tool_error_seen = True
                args = _first(tool, "arguments", "input")
                if isinstance(args, str):
                    try: json.loads(args)
                    except json.JSONDecodeError: current.invalid_tool_schema += 1
                elif args is not None and not isinstance(args, dict):
                    current.invalid_argument_type += 1
        if str(event.get("type", "")).lower() in {"tool_error", "toolresult_error"} and not any(
            child.get("error") or child.get("isError") for child in nested
        ):
            current.tool_errors += 1; tool_error_seen = True
        if event.get("recovered_after_tool_error") is True:
            current.recovered_after_tool_error = True
        if event.get("alternate_tool_used") is True:
            current.alternate_tool_used = True
    if current is not None:
        current.recovered_after_tool_error = tool_error_seen and (current.recovered_after_tool_error is not False)
        current.final_answer = last_text or None
        requests.append(current)
    for item in requests:
        item.__dict__.pop("_response_id", None)
    return requests
