from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .tools import AgentTool


def _load_config(path: str | Path) -> Mapping[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, Mapping):
        raise ValueError(f"External tools file must contain an object: {path}")
    return data


def _headers_from_config(raw_headers: Mapping[str, Any] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw_headers:
        return headers

    for key, value in raw_headers.items():
        if isinstance(value, str):
            headers[str(key)] = value
        elif isinstance(value, Mapping):
            env_name = value.get("env")
            prefix = value.get("prefix", "")
            if env_name:
                env_value = os.environ.get(str(env_name))
                if env_value:
                    headers[str(key)] = f"{prefix}{env_value}"
    return headers


def _make_http_tool(tool_cfg: Mapping[str, Any]) -> AgentTool:
    name = str(tool_cfg["name"])
    description = str(tool_cfg.get("description", f"External HTTP tool: {name}"))
    method = str(tool_cfg.get("method", "POST")).upper()
    url = str(tool_cfg["url"])
    timeout_s = int(tool_cfg.get("timeout_s", 120))
    input_schema = dict(tool_cfg.get("input_schema", {}))
    headers = _headers_from_config(tool_cfg.get("headers"))

    def call(args: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(args).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body if method != "GET" else None,
            method=method,
            headers={"Content-Type": "application/json", **headers},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"text": raw}
        return {
            "success": 200 <= status < 300,
            "status_code": status,
            "response": payload,
            "tool_source": "external_http",
            "url": url,
        }

    return AgentTool(name=name, description=description, input_schema=input_schema, func=call)


def load_external_tools(path: str | Path | None) -> dict[str, AgentTool]:
    """
    Load user-provided external HTTP tools from JSON/YAML.

    Expected format:
    {
      "tools": [
        {
          "name": "tool_name",
          "description": "...",
          "method": "POST",
          "url": "https://...",
          "headers": {"Authorization": {"env": "MY_API_KEY", "prefix": "Bearer "}},
          "input_schema": {"query": "string, required"}
        }
      ]
    }
    """
    if not path:
        return {}
    cfg = _load_config(path)
    tools_cfg = cfg.get("tools", [])
    if not isinstance(tools_cfg, list):
        raise ValueError("External tools config must contain a 'tools' list.")

    tools: dict[str, AgentTool] = {}
    for item in tools_cfg:
        if not isinstance(item, Mapping):
            raise ValueError("Each external tool entry must be an object.")
        tool = _make_http_tool(item)
        tools[tool.name] = tool
    return tools

