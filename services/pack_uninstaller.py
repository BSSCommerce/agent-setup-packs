"""Uninstall resources created from setup packs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.pack_install_status import query_installed_resources
from sqlalchemy.orm import Session

from core.agents.models import Agent

try:
    from plugins.agent_flow.models import AgentFlowDefinition
except ImportError:  # pragma: no cover - plugin availability is validated elsewhere
    AgentFlowDefinition = None  # type: ignore[assignment]

try:
    from plugins.deep_agent_builder.models import DeepAgentSubAgent
except ImportError:  # pragma: no cover - plugin availability is validated elsewhere
    DeepAgentSubAgent = None  # type: ignore[assignment]


@dataclass
class UninstalledResource:
    logical_key: str
    resource_type: str
    resource_id: int
    alias: str | None = None
    deleted: bool = False


@dataclass
class UninstallResult:
    catalog_key: str
    resources: list[UninstalledResource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def uninstall_pack_resources(
    db: Session,
    *,
    catalog_key: str,
    resource_type: str | None = None,
    logical_key: str | None = None,
) -> UninstallResult:
    """Delete latest installed resources for a pack, then remove their pack mappings."""
    from models import AgentSetupPackInstallation, AgentSetupPackResourceMap

    installed = query_installed_resources(db, catalog_key)
    selected = _select_resources(installed, resource_type=resource_type, logical_key=logical_key)
    result = UninstallResult(catalog_key=catalog_key)

    # Delete dependent resources first when uninstalling more than one resource.
    selected.sort(key=lambda item: _delete_order(item[0][0]))

    for (rtype, lkey), meta in selected:
        map_id = int(meta["map_id"])
        resource_id = int(meta["resource_id"])
        alias = meta.get("alias")
        deleted = _delete_resource(db, rtype, resource_id)
        resource_map = db.get(AgentSetupPackResourceMap, map_id)
        if resource_map is not None:
            db.delete(resource_map)
        result.resources.append(
            UninstalledResource(
                logical_key=lkey,
                resource_type=rtype,
                resource_id=resource_id,
                alias=alias,
                deleted=deleted,
            )
        )
        if not deleted:
            result.warnings.append(
                f"{rtype} '{lkey}' was already missing; removed setup-pack mapping only."
            )

    if not result.resources:
        return result

    db.flush()
    _mark_empty_installations_uninstalled(db, catalog_key, AgentSetupPackInstallation)
    db.commit()
    return result


def _select_resources(
    installed: dict[tuple[str, str], dict[str, Any]],
    *,
    resource_type: str | None,
    logical_key: str | None,
) -> list[tuple[tuple[str, str], dict[str, Any]]]:
    if resource_type and logical_key:
        meta = installed.get((resource_type, logical_key))
        return [((resource_type, logical_key), meta)] if meta else []
    return list(installed.items())


def _delete_order(resource_type: str) -> int:
    if resource_type == "flow":
        return 0
    if resource_type == "deep_agent":
        return 1
    return 2


def _delete_resource(db: Session, resource_type: str, resource_id: int) -> bool:
    if resource_type == "flow":
        if AgentFlowDefinition is None:
            return False
        row = db.get(AgentFlowDefinition, resource_id)
        if row is None:
            return False
        db.delete(row)
        return True

    if resource_type in {"agent", "deep_agent"}:
        row = db.get(Agent, resource_id)
        if row is None:
            return False
        if DeepAgentSubAgent is not None:
            db.query(DeepAgentSubAgent).filter(
                (DeepAgentSubAgent.deep_agent_id == resource_id)
                | (DeepAgentSubAgent.sub_agent_id == resource_id)
            ).delete(synchronize_session=False)
        db.delete(row)
        return True

    return False


def _mark_empty_installations_uninstalled(
    db: Session,
    catalog_key: str,
    installation_model,
) -> None:
    rows = db.query(installation_model).filter(installation_model.template_key == catalog_key).all()
    for row in rows:
        if row.status != "success":
            continue
        if not row.resources:
            row.status = "uninstalled"
