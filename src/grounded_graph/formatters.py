"""Output formatters for human, JSON, and Markdown output."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from grounded_graph.graph import GraphNode


class Formatter(ABC):
    @abstractmethod
    def format_status(self, data: dict[str, Any]) -> str: ...

    @abstractmethod
    def format_nodes(self, items: list[GraphNode]) -> str: ...

    @abstractmethod
    def format_path(self, items: list[GraphNode]) -> str: ...

    @abstractmethod
    def format_context(self, items: list[dict[str, Any]]) -> str: ...


class HumanFormatter(Formatter):
    def format_status(self, data: dict[str, Any]) -> str:
        lines = ["Graph Status", "============", ""]
        for key, value in data.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def format_nodes(self, items: list[GraphNode]) -> str:
        lines = []
        for node in items:
            sig = f"  {node.signature}" if node.signature else ""
            lines.append(f"{node.name} ({node.kind}) in {node.file_path}:{node.line_start}{sig}")
        return "\n".join(lines)

    def format_path(self, items: list[GraphNode]) -> str:
        if not items:
            return "No path found."
        return " -> ".join(f"{n.name} ({n.kind})" for n in items)

    def format_context(self, items: list[dict[str, Any]]) -> str:
        lines = []
        for item in items:
            lines.append(f"--- {item['symbol']} ({item['kind']}) [{item['role']}] ---")
            lines.append(f"File: {item['file']}:{item['lines'][0]}-{item['lines'][1]}")
            if item.get("docstring"):
                lines.append(f"Doc: {item['docstring']}")
            lines.append("```")
            lines.append(item["source"])
            lines.append("```")
            lines.append("")
        return "\n".join(lines)


class JsonFormatter(Formatter):
    def format_status(self, data: dict[str, Any]) -> str:
        return json.dumps({"status": data}, indent=2)

    def format_nodes(self, items: list[GraphNode]) -> str:
        return json.dumps(
            {
                "nodes": [
                    {
                        "name": n.name,
                        "kind": n.kind,
                        "file": n.file_path,
                        "line_start": n.line_start,
                        "line_end": n.line_end,
                        "signature": n.signature,
                    }
                    for n in items
                ]
            },
            indent=2,
        )

    def format_path(self, items: list[GraphNode]) -> str:
        return json.dumps(
            {
                "path": [
                    {"name": n.name, "kind": n.kind, "file": n.file_path, "line": n.line_start}
                    for n in items
                ]
            },
            indent=2,
        )

    def format_context(self, items: list[dict[str, Any]]) -> str:
        return json.dumps({"context": items, "partial": False}, indent=2)


class MarkdownFormatter(Formatter):
    def format_status(self, data: dict[str, Any]) -> str:
        lines = ["# Graph Status", ""]
        for key, value in data.items():
            lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)

    def format_nodes(self, items: list[GraphNode]) -> str:
        lines = []
        for node in items:
            sig = f"`{node.signature}`" if node.signature else ""
            lines.append(
                f"- `{node.name}` ({node.kind}) — `{node.file_path}:{node.line_start}` {sig}"
            )
        return "\n".join(lines)

    def format_path(self, items: list[GraphNode]) -> str:
        if not items:
            return "*No path found.*"
        parts = []
        for n in items:
            parts.append(f"`{n.name}`")
        return " -> ".join(parts)

    def format_context(self, items: list[dict[str, Any]]) -> str:
        lines = []
        for item in items:
            lines.append(f"## `{item['symbol']}` ({item['kind']}) — {item['role']}")
            lines.append(f"*File: `{item['file']}:{item['lines'][0]}`*")
            lines.append("")
            lines.append("```python")
            lines.append(item["source"])
            lines.append("```")
            lines.append("")
        return "\n".join(lines)


_FORMATTERS: dict[str, Formatter] = {
    "human": HumanFormatter(),
    "json": JsonFormatter(),
    "markdown": MarkdownFormatter(),
}


def get_formatter(name: str) -> Formatter:
    if name not in _FORMATTERS:
        raise ValueError(f"Unknown output format: {name}. Choose from: {list(_FORMATTERS)}")
    return _FORMATTERS[name]
