"""Build ecosystem graph data (nodes/edges) for pack relationship visualization."""

from __future__ import annotations

from typing import Any

from pack_catalog import SETUP_PACKS, get_pack_by_key
from services.pack_install_status import query_all_installed_resources
from services.pack_inventory import build_pack_inventory
from services.pack_loader import PackLoader, PackNotFoundError
from sqlalchemy.orm import Session


def _resource_classes(resource_type: str, is_installed: bool) -> str:
    state = "installed" if is_installed else "pending"
    return f"resource-node {state} {resource_type}"


def _pack_node_id(catalog_key: str) -> str:
    return f"pack:{catalog_key}"


def _resource_node_id(catalog_key: str, resource_type: str, logical_key: str) -> str:
    return f"res:{catalog_key}:{resource_type}:{logical_key}"


def _resolve_target_resource_type(
    target_inv: dict[str, Any], logical_key: str
) -> tuple[str, str]:
    for deep in target_inv.get("deep_agents") or []:
        if deep["logical_key"] == logical_key:
            return "deep_agent", deep["name"]
    for agent in target_inv.get("agents") or []:
        if agent["logical_key"] == logical_key:
            return "agent", agent["name"]
    for flow in target_inv.get("flows") or []:
        if flow["logical_key"] == logical_key:
            return "flow", flow["name"]
    if logical_key.endswith("_lead") or "coordinator" in logical_key or "commander" in logical_key:
        return "deep_agent", logical_key.replace("_", " ").title()
    return "agent", logical_key.replace("_", " ").title()


def build_ecosystem_graph(db: Session, *, loader: PackLoader | None = None) -> dict[str, Any]:
    """Return Cytoscape.js elements {nodes, edges} plus summary stats."""
    pack_loader = loader or PackLoader()
    installed_all = query_all_installed_resources(db)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    node_ids: set[str] = set()

    inventories: dict[str, dict[str, Any]] = {}
    loaded_flags: dict[str, bool] = {}

    for catalog in SETUP_PACKS:
        catalog_key = catalog["key"]
        try:
            loaded = pack_loader.load_pack(catalog_key=catalog_key)
            inventories[catalog_key] = build_pack_inventory(loaded)
            loaded_flags[catalog_key] = True
        except PackNotFoundError:
            loaded_flags[catalog_key] = False

    packs_on_disk = sum(1 for v in loaded_flags.values() if v)
    total_resources = 0
    installed_resources = 0

    for catalog in SETUP_PACKS:
        catalog_key = catalog["key"]
        accent = catalog.get("accent") or "sky"
        pack_id = _pack_node_id(catalog_key)
        installed_map = installed_all.get(catalog_key, {})
        pack_total = (
            catalog["stats"]["agents"]
            + catalog["stats"]["deep_agents"]
            + catalog["stats"]["flows"]
        )

        nodes.append(
            {
                "data": {
                    "id": pack_id,
                    "label": catalog["short_name"],
                    "type": "pack",
                    "catalog_key": catalog_key,
                    "name": catalog["name"],
                    "org_layer": catalog["org_layer"],
                    "org_layer_order": catalog["org_layer_order"],
                    "accent": accent,
                    "on_disk": loaded_flags.get(catalog_key, False),
                    "installed_count": len(installed_map),
                    "resource_count": pack_total,
                    "detail_url": f"/agent-setup-packs/packs/{catalog_key}",
                },
                "classes": "pack-node",
            }
        )
        node_ids.add(pack_id)

        inv = inventories.get(catalog_key)
        if not inv:
            continue

        for agent in inv["agents"]:
            total_resources += 1
            is_installed = ("agent", agent["logical_key"]) in installed_map
            if is_installed:
                installed_resources += 1
            _append_resource_node(
                nodes,
                node_ids,
                agent,
                catalog_key,
                "agent",
                is_installed,
                installed_map,
                accent,
            )

        for deep in inv["deep_agents"]:
            total_resources += 1
            is_installed = ("deep_agent", deep["logical_key"]) in installed_map
            if is_installed:
                installed_resources += 1
            _append_resource_node(
                nodes,
                node_ids,
                deep,
                catalog_key,
                "deep_agent",
                is_installed,
                installed_map,
                accent,
            )
            for sub in deep.get("required_sub_agents") or []:
                if not sub.get("in_pack"):
                    continue
                sub_key = sub["logical_key"]
                _add_edge(
                    edges,
                    edge_ids,
                    _resource_node_id(catalog_key, "deep_agent", deep["logical_key"]),
                    _resource_node_id(catalog_key, "agent", sub_key),
                    "sub_agent",
                    "coordinates",
                )

        for flow in inv["flows"]:
            total_resources += 1
            is_installed = ("flow", flow["logical_key"]) in installed_map
            if is_installed:
                installed_resources += 1
            _append_resource_node(
                nodes,
                node_ids,
                flow,
                catalog_key,
                "flow",
                is_installed,
                installed_map,
                accent,
            )

            agent_keys_in_flow: list[str] = []
            for req in flow.get("required_agents") or []:
                lkey = req.get("logical_key")
                if lkey and req.get("in_pack"):
                    _add_edge(
                        edges,
                        edge_ids,
                        _resource_node_id(catalog_key, "flow", flow["logical_key"]),
                        _resource_node_id(catalog_key, "agent", lkey),
                        "flow_requires",
                        "requires",
                    )
                    if lkey not in agent_keys_in_flow:
                        agent_keys_in_flow.append(lkey)

            for i in range(len(agent_keys_in_flow) - 1):
                _add_edge(
                    edges,
                    edge_ids,
                    _resource_node_id(catalog_key, "agent", agent_keys_in_flow[i]),
                    _resource_node_id(catalog_key, "agent", agent_keys_in_flow[i + 1]),
                    "flow_sequence",
                    "",
                )
            if agent_keys_in_flow:
                _add_edge(
                    edges,
                    edge_ids,
                    _resource_node_id(catalog_key, "flow", flow["logical_key"]),
                    _resource_node_id(catalog_key, "agent", agent_keys_in_flow[0]),
                    "flow_entry",
                    "starts",
                )

            for opt in flow.get("optional_nodes") or []:
                target_catalog = str(opt.get("pack") or "").strip()
                target_lkey = str(opt.get("logical_key") or "").strip()
                if not target_catalog or not target_lkey:
                    continue
                target_meta = get_pack_by_key(target_catalog)
                if target_meta is None:
                    continue
                target_inv = inventories.get(target_catalog, {})
                rtype, target_name = _resolve_target_resource_type(target_inv, target_lkey)
                target_installed = (rtype, target_lkey) in installed_all.get(target_catalog, {})
                _ensure_resource_node(
                    nodes,
                    node_ids,
                    target_catalog,
                    rtype,
                    target_lkey,
                    target_name,
                    target_meta.get("accent") or "sky",
                    target_installed,
                    installed_all.get(target_catalog, {}),
                )
                _add_edge(
                    edges,
                    edge_ids,
                    _resource_node_id(catalog_key, "flow", flow["logical_key"]),
                    _resource_node_id(target_catalog, rtype, target_lkey),
                    "cross_pack",
                    target_meta.get("short_name", target_catalog),
                    optional=True,
                    target_installed=target_installed,
                )

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "pack_count": len(SETUP_PACKS),
            "packs_on_disk": packs_on_disk,
            "total_resources": total_resources,
            "installed_resources": installed_resources,
            "edge_count": len(edges),
        },
        "legend": _legend_payload(),
    }


def _append_resource_node(
    nodes: list[dict[str, Any]],
    node_ids: set[str],
    item: dict[str, Any],
    catalog_key: str,
    resource_type: str,
    is_installed: bool,
    installed_map: dict[tuple[str, str], dict[str, Any]],
    pack_accent: str,
) -> None:
    nid = _resource_node_id(catalog_key, resource_type, item["logical_key"])
    if nid in node_ids:
        return
    node_ids.add(nid)
    meta = installed_map.get((resource_type, item["logical_key"]), {})
    label = item.get("name") or item["logical_key"]
    if len(label) > 24:
        label = label[:22] + "…"
    nodes.append(
        {
            "data": {
                "id": nid,
                "parent": _pack_node_id(catalog_key),
                "label": label,
                "type": resource_type,
                "resource_type": resource_type,
                "logical_key": item["logical_key"],
                "catalog_key": catalog_key,
                "installed": is_installed,
                "alias": meta.get("alias") if is_installed else None,
                "detail_url": meta.get("installed_url")
                if is_installed
                else f"/agent-setup-packs/packs/{catalog_key}",
                "pack_accent": pack_accent,
            },
            "classes": _resource_classes(resource_type, is_installed),
        }
    )


def _ensure_resource_node(
    nodes: list[dict[str, Any]],
    node_ids: set[str],
    catalog_key: str,
    resource_type: str,
    logical_key: str,
    name: str,
    pack_accent: str,
    is_installed: bool,
    installed_map: dict[tuple[str, str], dict[str, Any]],
) -> None:
    nid = _resource_node_id(catalog_key, resource_type, logical_key)
    if nid in node_ids:
        return
    node_ids.add(nid)
    meta = installed_map.get((resource_type, logical_key), {})
    label = name
    if len(label) > 24:
        label = label[:22] + "…"
    nodes.append(
        {
            "data": {
                "id": nid,
                "parent": _pack_node_id(catalog_key),
                "label": label,
                "type": resource_type,
                "resource_type": resource_type,
                "logical_key": logical_key,
                "catalog_key": catalog_key,
                "installed": is_installed,
                "alias": meta.get("alias") if is_installed else None,
                "detail_url": meta.get("installed_url")
                if is_installed
                else f"/agent-setup-packs/packs/{catalog_key}",
                "pack_accent": pack_accent,
                "cross_pack_ref": True,
            },
            "classes": _resource_classes(resource_type, is_installed),
        }
    )


def _add_edge(
    edges: list[dict[str, Any]],
    edge_ids: set[str],
    source: str,
    target: str,
    edge_type: str,
    label: str,
    *,
    optional: bool = False,
    target_installed: bool = False,
) -> None:
    eid = f"{source}|{edge_type}|{target}"
    if eid in edge_ids or source == target:
        return
    edge_ids.add(eid)
    edges.append(
        {
            "data": {
                "id": eid,
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "label": label,
                "optional": optional,
                "target_installed": target_installed,
            },
            "classes": f"edge-{edge_type}" + (" optional" if optional else ""),
        }
    )


def _legend_payload() -> list[dict[str, str]]:
    return [
        {"key": "agent_installed", "label": "Agent · installed", "color": "#10b981"},
        {"key": "agent_pending", "label": "Agent · not installed", "color": "#94a3b8"},
        {"key": "deep_installed", "label": "Deep agent · installed", "color": "#7c3aed"},
        {"key": "deep_pending", "label": "Deep agent · not installed", "color": "#c4b5fd"},
        {"key": "flow_installed", "label": "AgentFlow · installed", "color": "#059669"},
        {"key": "flow_pending", "label": "AgentFlow · not installed", "color": "#64748b"},
        {"key": "edge_sub", "label": "Deep → sub-agent", "color": "#8b5cf6"},
        {"key": "edge_flow", "label": "Flow → agent", "color": "#10b981"},
        {"key": "edge_cross", "label": "Cross-pack optional", "color": "#f59e0b"},
    ]
