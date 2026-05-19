"""Build pack inventory, dependency maps, and preview payloads for the admin UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from services.pack_loader import (
    AgentTemplate,
    DeepAgentTemplate,
    FlowTemplate,
    LoadedPack,
    PackLoader,
    PackNotFoundError,
)


def _agent_display_name(template: AgentTemplate) -> str:
    meta = template.data.get("agent") or {}
    return str(meta.get("name") or template.logical_key).strip()


def _deep_display_name(template: DeepAgentTemplate) -> str:
    meta = template.data.get("agent") or {}
    return str(meta.get("name") or template.logical_key).strip()


def _alias_suffix_from_flow_alias(agent_alias: str, flow_prefix: str) -> str | None:
    alias = (agent_alias or "").strip()
    prefix = (flow_prefix or "it").strip().lower().rstrip("_") + "_"
    if alias.startswith(prefix):
        return alias[len(prefix) :]
    if "_" in alias:
        return alias.split("_", 1)[1]
    return None


def _resolve_logical_key_from_alias_suffix(
    suffix: str | None, agents_by_suffix: dict[str, str]
) -> tuple[str | None, bool]:
    """Return (logical_key, in_pack)."""
    if not suffix:
        return None, False
    key = agents_by_suffix.get(suffix)
    if key:
        return key, True
    return suffix, False


def build_pack_inventory(loaded: LoadedPack) -> dict[str, Any]:
    """Serializable inventory for templates and APIs."""
    agents_by_key: dict[str, AgentTemplate] = {a.logical_key: a for a in loaded.agents}
    agents_by_suffix: dict[str, str] = {a.alias_suffix: a.logical_key for a in loaded.agents}
    deep_by_key: dict[str, DeepAgentTemplate] = {d.logical_key: d for d in loaded.deep_agents}

    agent_required_by_deep: dict[str, list[str]] = {k: [] for k in agents_by_key}
    agent_required_by_flow: dict[str, list[str]] = {k: [] for k in agents_by_key}

    agents_ui: list[dict[str, Any]] = []
    for template in loaded.agents:
        agents_ui.append(
            {
                "logical_key": template.logical_key,
                "name": _agent_display_name(template),
                "alias_suffix": template.alias_suffix,
                "description": (template.data.get("agent") or {}).get("description") or "",
                "skills_count": len(template.data.get("skills") or []),
                "source_file": template.source_path.name if template.source_path else "",
                "required_by_deep_agents": [],
                "required_by_flows": [],
            }
        )

    deep_ui: list[dict[str, Any]] = []
    for template in loaded.deep_agents:
        sub_requirements: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        for sub_key in template.sub_agent_logical_keys:
            in_pack = sub_key in agents_by_key
            sub_requirements.append(
                {
                    "logical_key": sub_key,
                    "name": _agent_display_name(agents_by_key[sub_key])
                    if in_pack
                    else sub_key.replace("_", " ").title(),
                    "alias_suffix": agents_by_key[sub_key].alias_suffix if in_pack else sub_key,
                    "in_pack": in_pack,
                }
            )
            if in_pack:
                agent_required_by_deep[sub_key].append(template.logical_key)
            else:
                missing.append({"logical_key": sub_key, "reason": "Not defined in this pack"})

        deep_ui.append(
            {
                "logical_key": template.logical_key,
                "name": _deep_display_name(template),
                "alias_suffix": template.alias_suffix,
                "description": (template.data.get("agent") or {}).get("description") or "",
                "is_async_subagents": bool(
                    (template.data.get("agent") or {}).get("is_async_subagents", True)
                ),
                "required_sub_agents": sub_requirements,
                "missing_sub_agents": missing,
                "sub_agent_count": len(template.sub_agent_logical_keys),
                "source_file": template.source_path.name if template.source_path else "",
            }
        )

    flows_ui: list[dict[str, Any]] = []
    for template in loaded.flows:
        node_requirements: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for node in template.flow.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            if str(node.get("type") or "agent").strip().lower() != "agent":
                continue
            alias = str(node.get("agent_alias") or "").strip()
            suffix = _alias_suffix_from_flow_alias(alias, template.alias_prefix)
            logical_key, in_pack = _resolve_logical_key_from_alias_suffix(suffix, agents_by_suffix)
            if logical_key and logical_key not in seen_keys:
                seen_keys.add(logical_key)
                if in_pack:
                    agent_required_by_flow[logical_key].append(template.logical_key)
            node_requirements.append(
                {
                    "node_id": str(node.get("id") or ""),
                    "label": str(node.get("label") or node.get("name") or ""),
                    "agent_alias": alias,
                    "logical_key": logical_key,
                    "in_pack": in_pack,
                }
            )

        optional_nodes = []
        for opt in template.metadata.get("optional_nodes") or []:
            if isinstance(opt, dict):
                optional_nodes.append(
                    {
                        "logical_key": str(opt.get("logical_key") or ""),
                        "pack": str(opt.get("pack") or ""),
                        "reason": str(opt.get("reason") or ""),
                        "insert_after": str(opt.get("insert_after") or ""),
                        "insert_before": str(opt.get("insert_before") or ""),
                    }
                )

        flows_ui.append(
            {
                "logical_key": template.logical_key,
                "name": template.name,
                "description": template.description,
                "alias_prefix": template.alias_prefix,
                "node_count": len(template.flow.get("nodes") or []),
                "required_agents": node_requirements,
                "optional_nodes": optional_nodes,
                "approval_notes": template.metadata.get("approval_notes") or [],
                "source_file": template.source_path.name if template.source_path else "",
            }
        )

    for item in agents_ui:
        key = item["logical_key"]
        item["required_by_deep_agents"] = [
            {"logical_key": dk, "name": _deep_display_name(deep_by_key[dk])}
            for dk in agent_required_by_deep.get(key, [])
        ]
        item["required_by_flows"] = [
            {
                "logical_key": fk,
                "name": next((f["name"] for f in flows_ui if f["logical_key"] == fk), fk),
            }
            for fk in agent_required_by_flow.get(key, [])
        ]

    install_order = [a.logical_key for a in loaded.agents]
    install_order += [d.logical_key for d in loaded.deep_agents]
    install_order += [f.logical_key for f in loaded.flows]

    return {
        "pack_slug": loaded.manifest.slug,
        "version": loaded.manifest.version,
        "agents": agents_ui,
        "deep_agents": deep_ui,
        "flows": flows_ui,
        "install_order": install_order,
        "summary": {
            "agents": len(agents_ui),
            "deep_agents": len(deep_ui),
            "flows": len(flows_ui),
        },
    }


def get_resource_preview(
    loaded: LoadedPack,
    *,
    resource_type: str,
    logical_key: str,
) -> dict[str, Any]:
    """Return preview metadata and source content for one pack resource."""
    rtype = (resource_type or "").strip().lower()
    key = (logical_key or "").strip()
    if not key:
        raise ValueError("logical_key is required")

    if rtype == "agent":
        template = next((a for a in loaded.agents if a.logical_key == key), None)
        if template is None:
            raise PackNotFoundError(f"Agent '{key}' not found in pack.")
        return _preview_from_template(
            resource_type="agent",
            logical_key=key,
            title=_agent_display_name(template),
            source_path=template.source_path,
            data=template.data,
            dependencies=_agent_dependencies_summary(loaded, key),
        )

    if rtype == "deep_agent":
        template = next((d for d in loaded.deep_agents if d.logical_key == key), None)
        if template is None:
            raise PackNotFoundError(f"Deep agent '{key}' not found in pack.")
        inv = build_pack_inventory(loaded)
        deep_item = next((d for d in inv["deep_agents"] if d["logical_key"] == key), {})
        return _preview_from_template(
            resource_type="deep_agent",
            logical_key=key,
            title=_deep_display_name(template),
            source_path=template.source_path,
            data=template.data,
            dependencies={
                "required_sub_agents": deep_item.get("required_sub_agents") or [],
                "missing_sub_agents": deep_item.get("missing_sub_agents") or [],
            },
            extra_fields={"sub_agents": template.sub_agent_logical_keys},
        )

    if rtype == "flow":
        template = next((f for f in loaded.flows if f.logical_key == key), None)
        if template is None:
            raise PackNotFoundError(f"Flow '{key}' not found in pack.")
        inv = build_pack_inventory(loaded)
        flow_item = next((f for f in inv["flows"] if f["logical_key"] == key), {})
        wrapper = {
            "version": "1",
            "logical_key": template.logical_key,
            "name": template.name,
            "description": template.description,
            "status": template.status,
            "alias_prefix": template.alias_prefix,
            **{
                k: v
                for k, v in template.metadata.items()
                if k not in {"logical_key", "name", "description", "status", "alias_prefix"}
            },
            "flow": template.flow,
        }
        return {
            "resource_type": "flow",
            "logical_key": key,
            "title": template.name,
            "format": "json",
            "source_file": template.source_path.name if template.source_path else "",
            "content": json.dumps(wrapper, indent=2, ensure_ascii=False),
            "summary": _flow_summary(template, flow_item),
            "dependencies": {
                "required_agents": flow_item.get("required_agents") or [],
                "optional_nodes": flow_item.get("optional_nodes") or [],
            },
            "structured": wrapper,
        }

    raise ValueError(f"Unknown resource_type '{resource_type}'.")


def _preview_from_template(
    *,
    resource_type: str,
    logical_key: str,
    title: str,
    source_path: Path | None,
    data: dict[str, Any],
    dependencies: dict[str, Any],
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(data)
    if extra_fields:
        payload = {**payload, **extra_fields}
    content = ""
    if source_path and source_path.is_file():
        content = source_path.read_text(encoding="utf-8")
    else:
        content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)

    return {
        "resource_type": resource_type,
        "logical_key": logical_key,
        "title": title,
        "format": "yaml",
        "source_file": source_path.name if source_path else "",
        "content": content,
        "summary": _agent_summary(payload),
        "dependencies": dependencies,
        "structured": payload,
    }


def _agent_summary(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.get("agent") or {}
    skills = data.get("skills") or []
    tool_config = data.get("tool_config") or {}
    enabled_tools = [k for k, v in tool_config.items() if v]
    return {
        "name": meta.get("name"),
        "alias_suffix": data.get("alias_suffix"),
        "status": meta.get("status"),
        "skills_count": len(skills),
        "skill_names": [s.get("name") for s in skills if isinstance(s, dict)],
        "enabled_tools": enabled_tools,
        "prompt_keys": list((data.get("prompts") or {}).keys()),
    }


def _flow_summary(template: FlowTemplate, flow_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": template.name,
        "description": template.description,
        "status": template.status,
        "alias_prefix": template.alias_prefix,
        "node_count": flow_item.get("node_count"),
        "agent_nodes": len(flow_item.get("required_agents") or []),
    }


def _agent_dependencies_summary(loaded: LoadedPack, logical_key: str) -> dict[str, Any]:
    inv = build_pack_inventory(loaded)
    agent_item = next((a for a in inv["agents"] if a["logical_key"] == logical_key), {})
    return {
        "required_by_deep_agents": agent_item.get("required_by_deep_agents") or [],
        "required_by_flows": agent_item.get("required_by_flows") or [],
    }


def load_inventory_for_catalog(catalog_key: str) -> dict[str, Any]:
    from pack_catalog import get_pack_slug_for_key

    slug = get_pack_slug_for_key(catalog_key)
    if not slug:
        raise PackNotFoundError(f"Unknown catalog key '{catalog_key}'.")
    loaded = PackLoader().load_pack(slug=slug)
    return build_pack_inventory(loaded)
