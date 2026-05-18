"""Merge pack tool_config with install-time tool profiles."""

from __future__ import annotations

from typing import Any

KNOWN_TOOL_KEYS: frozenset[str] = frozenset(
    {
        "enable_memory_tools",
        "enable_gitdocs_search_tools",
        "enable_jira_tools",
        "enable_gitlab_tools",
        "enable_google_drive_tools",
        "enable_browser_tools",
        "enable_cursor_cli_tool",
        "enable_claude_cli_tool",
        "enable_query_codebase_tools",
        "enable_file_tools",
        "enable_shell_tool",
        "enable_websearch_tool",
        "enable_todos_tools",
    }
)


def _normalize_base(base_config: dict[str, Any] | None) -> dict[str, bool]:
    raw = dict(base_config or {})
    return {key: bool(raw[key]) for key in KNOWN_TOOL_KEYS if key in raw}


def apply_tool_profile(base_config: dict[str, Any] | None, profile: str) -> dict[str, bool]:
    """Return final boolean tool_config for an agent row."""
    normalized = _normalize_base(base_config)
    profile = (profile or "read_only").strip().lower()

    if profile == "prompt_only":
        return {key: False for key in normalized}

    if profile == "read_only":
        result = {key: False for key in normalized}
        if normalized.get("enable_memory_tools"):
            result["enable_memory_tools"] = True
        if "enable_gitdocs_search_tools" in normalized:
            result["enable_gitdocs_search_tools"] = bool(normalized["enable_gitdocs_search_tools"])
        else:
            result["enable_gitdocs_search_tools"] = True
        return result

    return dict(normalized)


def tool_config_to_json(config: dict[str, bool]) -> str:
    import json

    return json.dumps(config, ensure_ascii=False)
