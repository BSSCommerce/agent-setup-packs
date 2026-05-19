"""Routes for Agent Setup Packs plugin."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth.service import get_current_user_from_request
from core.database.base import get_db
from core.plugin_sdk.registry import get_registry
from core.template_env import get_templates

_PLUGIN_ROOT = Path(__file__).resolve().parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from models import AgentSetupPackInstallation  # noqa: E402
from pack_catalog import (  # noqa: E402
    ORG_LAYERS,
    PRIMITIVE_LEGEND,
    SETUP_PACKS,
    catalog_totals,
    get_pack_by_key,
    get_pack_slug_for_key,
)
from services.install_options import InstallOptions  # noqa: E402
from services.pack_graph import (  # noqa: E402
    build_ecosystem_graph,
    legend_force_graph_3d,
    to_force_graph_3d,
)
from services.pack_install_status import (  # noqa: E402
    apply_install_status_to_inventory,
    query_all_installed_resources,
    query_installed_resources,
)
from services.pack_installer import PackInstaller, PackInstallerError  # noqa: E402
from services.pack_inventory import get_resource_preview, load_inventory_for_catalog  # noqa: E402
from services.pack_loader import PackLoader, PackNotFoundError  # noqa: E402
from services.pack_uninstaller import uninstall_pack_resources  # noqa: E402

router = APIRouter(prefix="/agent-setup-packs", tags=["agent-setup-packs"])


def _auth_or_redirect(db: Session, request: Request):
    user = get_current_user_from_request(db, request)
    if user is None:
        return None, RedirectResponse(url="/login", status_code=303)
    return user, None


def _auth_or_401(db: Session, request: Request):
    user = get_current_user_from_request(db, request)
    if user is None:
        return None, JSONResponse(status_code=401, content={"detail": "Authentication required"})
    return user, None


def _pack_available_on_disk(catalog_key: str) -> bool:
    slug = get_pack_slug_for_key(catalog_key)
    if not slug:
        return False
    try:
        PackLoader().load_manifest(slug)
        return True
    except PackNotFoundError:
        return False


def _serialize_plan(plan) -> dict[str, Any]:
    return {
        "ok": plan.ok,
        "pack_slug": plan.pack_slug,
        "catalog_key": plan.catalog_key,
        "version": plan.version,
        "warnings": plan.warnings,
        "errors": plan.errors,
        "resources": [
            {
                "logical_key": r.logical_key,
                "resource_type": r.resource_type,
                "alias": r.alias,
                "name": r.name,
                "action": r.action,
                "detail": r.detail,
            }
            for r in plan.resources
        ],
    }


def _serialize_install_result(result) -> dict[str, Any]:
    payload = {
        "dry_run": result.dry_run,
        "installation_id": result.installation_id,
        "plan": _serialize_plan(result.plan),
        "resources": [
            {
                "logical_key": r.logical_key,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "alias": r.alias,
            }
            for r in result.resources
        ],
    }
    return payload


def _serialize_uninstall_result(result) -> dict[str, Any]:
    return {
        "catalog_key": result.catalog_key,
        "warnings": result.warnings,
        "resources": [
            {
                "logical_key": row.logical_key,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "alias": row.alias,
                "deleted": row.deleted,
            }
            for row in result.resources
        ],
    }


class InstallPackPayload(BaseModel):
    alias_prefix: str = Field(default="it", max_length=32)
    tool_profile: str = Field(default="integrated")
    flow_status: str = Field(default="draft")
    visibility: str = Field(default="creator")
    on_alias_conflict: str = Field(default="fail")
    dry_run: bool = False
    extra_tags: list[str] = Field(default_factory=list)


@router.get("", include_in_schema=False)
async def setup_packs_overview_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = _auth_or_redirect(db, request)
    if redirect:
        return redirect

    installations = (
        db.query(AgentSetupPackInstallation)
        .order_by(AgentSetupPackInstallation.created_at.desc())
        .limit(20)
        .all()
    )
    installed_by_key: dict[str, int] = {}
    for row in installations:
        if row.status == "success":
            installed_by_key[row.template_key] = installed_by_key.get(row.template_key, 0) + 1

    all_installed = query_all_installed_resources(db)
    install_status_by_key: dict[str, dict[str, Any]] = {}
    for pack in SETUP_PACKS:
        key = pack["key"]
        stats = pack["stats"]
        total = stats["agents"] + stats["deep_agents"] + stats["flows"]
        installed_count = len(all_installed.get(key, {}))
        install_status_by_key[key] = {
            "installed": installed_count,
            "total": total,
            "partial": 0 < installed_count < total,
            "complete": total > 0 and installed_count >= total,
            "on_disk": _pack_available_on_disk(key),
        }

    packs_by_layer: dict[int, list] = {}
    for pack in SETUP_PACKS:
        packs_by_layer.setdefault(pack["org_layer_order"], []).append(pack)

    registry = get_registry()
    return get_templates().TemplateResponse(
        request=request,
        name="setup_packs_overview.html",
        context={
            "request": request,
            "user": user,
            "registry": registry,
            "active_page": "agent_setup_packs",
            "packs": SETUP_PACKS,
            "packs_by_layer": packs_by_layer,
            "org_layers": ORG_LAYERS,
            "primitive_legend": PRIMITIVE_LEGEND,
            "catalog_totals": catalog_totals(),
            "installed_by_key": installed_by_key,
            "install_status_by_key": install_status_by_key,
            "recent_installations": installations,
        },
    )


@router.get("/api/ecosystem-graph")
async def ecosystem_graph_api(request: Request, db: Session = Depends(get_db)):
    user, err = _auth_or_401(db, request)
    if err:
        return err

    try:
        graph = build_ecosystem_graph(db, loader=PackLoader())
    except PackNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    force3d = to_force_graph_3d(graph)
    return JSONResponse(
        content={
            "graph": force3d,
            "summary": graph["summary"],
            "legend": legend_force_graph_3d(),
        }
    )


@router.get("/packs/{pack_key}", include_in_schema=False)
async def setup_pack_detail_page(
    pack_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user, redirect = _auth_or_redirect(db, request)
    if redirect:
        return redirect

    pack = get_pack_by_key(pack_key)
    if pack is None:
        return RedirectResponse(url="/agent-setup-packs", status_code=303)

    installations = (
        db.query(AgentSetupPackInstallation)
        .filter(AgentSetupPackInstallation.template_key == pack_key)
        .order_by(AgentSetupPackInstallation.created_at.desc())
        .limit(10)
        .all()
    )

    pack_slug = get_pack_slug_for_key(pack_key)
    pack_on_disk = _pack_available_on_disk(pack_key)
    pack_inventory: dict[str, Any] | None = None
    if pack_on_disk and pack_slug:
        try:
            pack_inventory = load_inventory_for_catalog(pack_key)
            installed = query_installed_resources(db, pack_key)
            pack_inventory = apply_install_status_to_inventory(pack_inventory, installed)
        except PackNotFoundError:
            pack_on_disk = False

    registry = get_registry()
    return get_templates().TemplateResponse(
        request=request,
        name="setup_pack_detail.html",
        context={
            "request": request,
            "user": user,
            "registry": registry,
            "active_page": "agent_setup_packs",
            "pack": pack,
            "pack_key": pack_key,
            "pack_slug": pack_slug,
            "pack_on_disk": pack_on_disk,
            "pack_inventory": pack_inventory,
            "primitive_legend": PRIMITIVE_LEGEND,
            "installations": installations,
        },
    )


@router.post("/api/packs/{pack_key}/dry-run")
async def dry_run_pack_api(
    pack_key: str,
    payload: InstallPackPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user, err = _auth_or_401(db, request)
    if err:
        return err

    if get_pack_by_key(pack_key) is None:
        return JSONResponse(status_code=404, content={"detail": "Pack not found in catalog."})

    options = InstallOptions(
        alias_prefix=payload.alias_prefix,
        tool_profile=payload.tool_profile,
        flow_status=payload.flow_status,
        visibility=payload.visibility,
        on_alias_conflict=payload.on_alias_conflict,
        dry_run=True,
        extra_tags=payload.extra_tags,
    ).normalized()

    installer = PackInstaller()
    plan = installer.plan(db, catalog_key=pack_key, options=options)
    return JSONResponse(content=_serialize_plan(plan))


@router.post("/api/packs/{pack_key}/resources/{resource_type}/{logical_key}/dry-run")
async def dry_run_resource_api(
    pack_key: str,
    resource_type: str,
    logical_key: str,
    payload: InstallPackPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user, err = _auth_or_401(db, request)
    if err:
        return err

    if get_pack_by_key(pack_key) is None:
        return JSONResponse(status_code=404, content={"detail": "Pack not found in catalog."})

    options = InstallOptions(
        alias_prefix=payload.alias_prefix,
        tool_profile=payload.tool_profile,
        flow_status=payload.flow_status,
        visibility=payload.visibility,
        on_alias_conflict=payload.on_alias_conflict,
        dry_run=True,
        extra_tags=payload.extra_tags,
    ).normalized()

    installer = PackInstaller()
    plan = installer.plan_resource(
        db,
        catalog_key=pack_key,
        resource_type=resource_type,
        logical_key=logical_key,
        options=options,
    )
    return JSONResponse(content=_serialize_plan(plan))


@router.post("/api/packs/{pack_key}/resources/{resource_type}/{logical_key}/install")
async def install_resource_api(
    pack_key: str,
    resource_type: str,
    logical_key: str,
    payload: InstallPackPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user, err = _auth_or_401(db, request)
    if err:
        return err

    if get_pack_by_key(pack_key) is None:
        return JSONResponse(status_code=404, content={"detail": "Pack not found in catalog."})

    options = InstallOptions(
        alias_prefix=payload.alias_prefix,
        tool_profile=payload.tool_profile,
        flow_status=payload.flow_status,
        visibility=payload.visibility,
        on_alias_conflict=payload.on_alias_conflict,
        dry_run=False,
        extra_tags=payload.extra_tags,
    ).normalized()

    installer = PackInstaller()
    try:
        result = installer.install_resource(
            db,
            catalog_key=pack_key,
            resource_type=resource_type,
            logical_key=logical_key,
            options=options,
            user_id=str(getattr(user, "id", "") or "") or None,
        )
    except PackInstallerError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    status = 200 if result.plan.ok else 400
    return JSONResponse(content=_serialize_install_result(result), status_code=status)


@router.post("/api/packs/{pack_key}/install")
async def install_pack_api(
    pack_key: str,
    payload: InstallPackPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user, err = _auth_or_401(db, request)
    if err:
        return err

    if get_pack_by_key(pack_key) is None:
        return JSONResponse(status_code=404, content={"detail": "Pack not found in catalog."})

    options = InstallOptions(
        alias_prefix=payload.alias_prefix,
        tool_profile=payload.tool_profile,
        flow_status=payload.flow_status,
        visibility=payload.visibility,
        on_alias_conflict=payload.on_alias_conflict,
        dry_run=payload.dry_run,
        extra_tags=payload.extra_tags,
    ).normalized()

    installer = PackInstaller()
    try:
        result = installer.install(
            db,
            catalog_key=pack_key,
            options=options,
            user_id=str(getattr(user, "id", "") or "") or None,
        )
    except PackInstallerError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    status = 200 if result.plan.ok else 400
    return JSONResponse(content=_serialize_install_result(result), status_code=status)


@router.post("/api/packs/{pack_key}/uninstall")
async def uninstall_pack_api(
    pack_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    _, err = _auth_or_401(db, request)
    if err:
        return err

    if get_pack_by_key(pack_key) is None:
        return JSONResponse(status_code=404, content={"detail": "Pack not found in catalog."})

    result = uninstall_pack_resources(db, catalog_key=pack_key)
    status = 200 if result.resources else 404
    return JSONResponse(content=_serialize_uninstall_result(result), status_code=status)


@router.post("/api/packs/{pack_key}/resources/{resource_type}/{logical_key}/uninstall")
async def uninstall_resource_api(
    pack_key: str,
    resource_type: str,
    logical_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    _, err = _auth_or_401(db, request)
    if err:
        return err

    if get_pack_by_key(pack_key) is None:
        return JSONResponse(status_code=404, content={"detail": "Pack not found in catalog."})

    result = uninstall_pack_resources(
        db,
        catalog_key=pack_key,
        resource_type=resource_type,
        logical_key=logical_key,
    )
    status = 200 if result.resources else 404
    return JSONResponse(content=_serialize_uninstall_result(result), status_code=status)


@router.get("/api/packs/{pack_key}/preview/{resource_type}/{logical_key}")
async def pack_resource_preview_api(
    pack_key: str,
    resource_type: str,
    logical_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    _, err = _auth_or_401(db, request)
    if err:
        return err

    slug = get_pack_slug_for_key(pack_key)
    if not slug:
        return JSONResponse(status_code=404, content={"detail": "Unknown catalog pack."})

    try:
        loaded = PackLoader().load_pack(slug=slug)
        preview = get_resource_preview(
            loaded, resource_type=resource_type, logical_key=logical_key
        )
    except PackNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return JSONResponse(content=preview)


@router.get("/api/packs/{pack_key}/inventory")
async def pack_inventory_api(pack_key: str, request: Request, db: Session = Depends(get_db)):
    _, err = _auth_or_401(db, request)
    if err:
        return err

    try:
        inventory = load_inventory_for_catalog(pack_key)
    except PackNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return JSONResponse(content=inventory)


@router.get("/api/packs/{pack_key}/manifest")
async def pack_manifest_api(pack_key: str, request: Request, db: Session = Depends(get_db)):
    _, err = _auth_or_401(db, request)
    if err:
        return err

    slug = get_pack_slug_for_key(pack_key)
    if not slug:
        return JSONResponse(status_code=404, content={"detail": "Unknown catalog pack."})

    try:
        loaded = PackLoader().load_pack(slug=slug)
    except PackNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return JSONResponse(
        content={
            "slug": loaded.manifest.slug,
            "catalog_key": loaded.manifest.catalog_key,
            "version": loaded.manifest.version,
            "name": loaded.manifest.name,
            "description": loaded.manifest.description,
            "counts": {
                "agents": len(loaded.agents),
                "deep_agents": len(loaded.deep_agents),
                "flows": len(loaded.flows),
            },
        }
    )
