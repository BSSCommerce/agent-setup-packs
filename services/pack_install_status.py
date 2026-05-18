"""Resolve which pack resources are already installed (from installation records)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def query_installed_resources(
    db: Session,
    catalog_key: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Map (resource_type, logical_key) → latest successful install metadata."""
    all_by_catalog = query_all_installed_resources(db)
    return dict(all_by_catalog.get(catalog_key, {}))


def query_all_installed_resources(
    db: Session,
) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    """Map catalog_key → (resource_type, logical_key) → install metadata."""
    from models import AgentSetupPackInstallation, AgentSetupPackResourceMap

    rows = (
        db.query(AgentSetupPackResourceMap)
        .join(AgentSetupPackInstallation)
        .filter(AgentSetupPackInstallation.status == "success")
        .order_by(
            AgentSetupPackInstallation.created_at.desc(),
            AgentSetupPackResourceMap.id.desc(),
        )
        .all()
    )

    by_catalog: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for row in rows:
        catalog_key = row.installation.template_key
        key = (row.resource_type, row.logical_key)
        catalog_map = by_catalog.setdefault(catalog_key, {})
        if key in catalog_map:
            continue
        catalog_map[key] = {
            "resource_id": row.resource_id,
            "alias": row.alias,
            "installation_id": row.installation_id,
            "installed_url": _resource_url(row.resource_type, row.resource_id),
        }
    return by_catalog


def _resource_url(resource_type: str, resource_id: int) -> str:
    if resource_type == "agent":
        return f"/agents/{resource_id}"
    if resource_type == "deep_agent":
        return f"/deep-agents/{resource_id}"
    if resource_type == "flow":
        return f"/agent-flow/designer?flow_id={resource_id}"
    return ""


def apply_install_status_to_inventory(
    inventory: dict[str, Any],
    installed: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Set ``installed`` flags and metadata on inventory agent / deep / flow items."""
    by_agent = {
        logical_key: meta
        for (rtype, logical_key), meta in installed.items()
        if rtype == "agent"
    }
    by_deep = {
        logical_key: meta
        for (rtype, logical_key), meta in installed.items()
        if rtype == "deep_agent"
    }
    by_flow = {
        logical_key: meta
        for (rtype, logical_key), meta in installed.items()
        if rtype == "flow"
    }

    for agent in inventory.get("agents") or []:
        _apply_item_status(agent, by_agent.get(agent["logical_key"]))

    for deep in inventory.get("deep_agents") or []:
        _apply_item_status(deep, by_deep.get(deep["logical_key"]))
        for sub in deep.get("required_sub_agents") or []:
            sub_key = sub.get("logical_key")
            if sub_key and sub_key in by_agent:
                _apply_item_status(sub, by_agent[sub_key])

    for flow in inventory.get("flows") or []:
        _apply_item_status(flow, by_flow.get(flow["logical_key"]))

    installed_count = sum(1 for item in (inventory.get("agents") or []) if item.get("installed"))
    installed_count += sum(
        1 for item in (inventory.get("deep_agents") or []) if item.get("installed")
    )
    installed_count += sum(1 for item in (inventory.get("flows") or []) if item.get("installed"))
    summary = inventory.setdefault("summary", {})
    summary["installed_total"] = installed_count

    return inventory


def _apply_item_status(item: dict[str, Any], meta: dict[str, Any] | None) -> None:
    if not meta:
        item["installed"] = False
        item["installed_alias"] = None
        item["installed_resource_id"] = None
        item["installed_url"] = None
        return
    item["installed"] = True
    item["installed_alias"] = meta.get("alias")
    item["installed_resource_id"] = meta.get("resource_id")
    item["installed_url"] = meta.get("installed_url")
