"""Install setup packs into Agent Manager (agents, deep agents, flows)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from services.install_options import InstallOptions, InstallSelection
from services.pack_loader import (
    AgentTemplate,
    DeepAgentTemplate,
    FlowTemplate,
    LoadedPack,
    PackLoader,
    PackNotFoundError,
)
from services.tool_profiles import apply_tool_profile, tool_config_to_json
from sqlalchemy.orm import Session

from core.agents.models import (
    Agent,
    AgentPrompt,
    AgentSetting,
    AgentSkill,
    AgentToolConfig,
    AgentToolLimitConfig,
    AgentToolPolicyConfig,
)
from core.agents.skill_tags import normalize_skill_tags

_ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class PackInstallerError(ValueError):
    """Installation failed with a user-facing message."""


@dataclass
class PlannedResource:
    logical_key: str
    resource_type: str
    alias: str
    name: str
    action: str = "create"
    detail: str = ""


@dataclass
class InstallPlan:
    pack_slug: str
    catalog_key: str
    version: str
    options: InstallOptions
    resources: list[PlannedResource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class InstalledResource:
    logical_key: str
    resource_type: str
    resource_id: int
    alias: str


@dataclass
class InstallResult:
    installation_id: int | None
    plan: InstallPlan
    resources: list[InstalledResource] = field(default_factory=list)
    dry_run: bool = False


def normalize_alias_prefix(prefix: str) -> str:
    raw = (prefix or "it").strip().lower().rstrip("_")
    raw = re.sub(r"[^a-z0-9_-]+", "_", raw).strip("_")
    return raw or "it"


def build_alias(prefix: str, alias_suffix: str) -> str:
    p = normalize_alias_prefix(prefix)
    suffix = (alias_suffix or "").strip().lower().strip("_")
    suffix = re.sub(r"[^a-z0-9_-]+", "_", suffix).strip("_")
    if not suffix:
        raise PackInstallerError("alias_suffix is required.")
    alias = f"{p}_{suffix}"
    if not _ALIAS_PATTERN.fullmatch(alias):
        raise PackInstallerError(f"Invalid alias '{alias}'.")
    return alias


def rewrite_flow_agent_aliases(
    flow: dict[str, Any],
    *,
    target_prefix: str,
    source_prefix: str,
) -> dict[str, Any]:
    """Deep-copy flow and rewrite agent_alias values to match install prefix."""
    flow_copy = json.loads(json.dumps(flow))
    target = normalize_alias_prefix(target_prefix)
    source = normalize_alias_prefix(source_prefix)
    source_token = f"{source}_"

    for node in flow_copy.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        alias = str(node.get("agent_alias") or "").strip()
        if not alias:
            continue
        if alias.startswith(source_token):
            suffix = alias[len(source_token) :]
            node["agent_alias"] = f"{target}_{suffix}"
        elif "_" in alias:
            # Best-effort: replace first segment if it matches source prefix
            parts = alias.split("_", 1)
            if len(parts) == 2 and parts[0] == source:
                node["agent_alias"] = f"{target}_{parts[1]}"

    return flow_copy


class PackInstaller:
    """Generic installer for any on-disk setup pack."""

    def __init__(self, loader: PackLoader | None = None) -> None:
        self.loader = loader or PackLoader()

    def plan_resource(
        self,
        db: Session,
        *,
        catalog_key: str | None = None,
        slug: str | None = None,
        resource_type: str,
        logical_key: str,
        options: InstallOptions | None = None,
    ) -> InstallPlan:
        opts = options or InstallOptions()
        opts.selection = InstallSelection.single(resource_type, logical_key)
        return self.plan(db, catalog_key=catalog_key, slug=slug, options=opts)

    def install_resource(
        self,
        db: Session,
        *,
        catalog_key: str | None = None,
        slug: str | None = None,
        resource_type: str,
        logical_key: str,
        options: InstallOptions | None = None,
        user_id: str | None = None,
    ) -> InstallResult:
        opts = options or InstallOptions()
        opts.selection = InstallSelection.single(resource_type, logical_key)
        return self.install(
            db,
            catalog_key=catalog_key,
            slug=slug,
            options=opts,
            user_id=user_id,
        )

    def plan(
        self,
        db: Session,
        *,
        catalog_key: str | None = None,
        slug: str | None = None,
        options: InstallOptions | None = None,
    ) -> InstallPlan:
        opts = (options or InstallOptions()).normalized()
        try:
            pack = self.loader.load_pack(catalog_key=catalog_key, slug=slug)
        except PackNotFoundError as exc:
            plan = InstallPlan(
                pack_slug=slug or "",
                catalog_key=catalog_key or "",
                version="",
                options=opts,
            )
            plan.errors.append(str(exc))
            return plan

        plan = InstallPlan(
            pack_slug=pack.manifest.slug,
            catalog_key=pack.manifest.catalog_key,
            version=pack.manifest.version,
            options=opts,
        )
        self._validate_pack(pack, plan)
        self._validate_flow_templates(pack, plan, opts)
        if plan.errors:
            return plan

        agents, deep_agents, flows = self._selected_templates(pack, opts.selection)
        if not agents and not deep_agents and not flows:
            plan.errors.append("No resources matched the install selection.")

        alias_map = self._planned_aliases(pack, opts)
        installing_agent_keys = {a.logical_key for a in agents}
        pending_agent_aliases = {
            alias_map[key] for key in installing_agent_keys if key in alias_map
        }
        for template in agents:
            alias = alias_map[template.logical_key]
            action = self._alias_action(db, alias, opts)
            if action == "conflict":
                plan.errors.append(f"Alias already exists: {alias}")
            plan.resources.append(
                PlannedResource(
                    logical_key=template.logical_key,
                    resource_type="agent",
                    alias=alias,
                    name=self._agent_name(template),
                    action=action,
                )
            )

        for template in deep_agents:
            alias = alias_map[template.logical_key]
            missing_pack = [
                key for key in template.sub_agent_logical_keys
                if key not in {a.logical_key for a in pack.agents}
            ]
            detail = f"sub-agents: {', '.join(template.sub_agent_logical_keys)}"
            if missing_pack:
                plan.errors.append(
                    f"Deep agent '{template.logical_key}' references unknown sub-agents in pack: "
                    + ", ".join(missing_pack)
                )
            missing_db = self._missing_sub_agents_in_db(
                db,
                pack,
                template,
                opts,
                alias_map,
                installing_keys=installing_agent_keys,
            )
            if missing_db:
                plan.errors.append(
                    f"Deep agent '{template.logical_key}' requires sub-agents not installed: "
                    + ", ".join(missing_db)
                )
            action = self._alias_action(db, alias, opts)
            if action == "conflict":
                plan.errors.append(f"Alias already exists: {alias}")
            plan.resources.append(
                PlannedResource(
                    logical_key=template.logical_key,
                    resource_type="deep_agent",
                    alias=alias,
                    name=self._agent_name(template),
                    action=action,
                    detail=detail,
                )
            )

        for template in flows:
            flow_json = rewrite_flow_agent_aliases(
                template.flow,
                target_prefix=opts.alias_prefix,
                source_prefix=template.alias_prefix,
            )
            missing_agents = [
                alias
                for alias in self._missing_flow_agent_aliases(db, flow_json)
                if alias not in pending_agent_aliases
            ]
            detail = f"status={opts.flow_status}"
            if missing_agents:
                plan.errors.append(
                    f"Flow '{template.logical_key}' requires agents not in database: "
                    + ", ".join(missing_agents)
                )
                detail += f"; missing: {', '.join(missing_agents)}"
            plan.resources.append(
                PlannedResource(
                    logical_key=template.logical_key,
                    resource_type="flow",
                    alias="",
                    name=template.name,
                    action="create",
                    detail=detail,
                )
            )

        return plan

    def install(
        self,
        db: Session,
        *,
        catalog_key: str | None = None,
        slug: str | None = None,
        options: InstallOptions | None = None,
        user_id: str | None = None,
    ) -> InstallResult:
        from models import AgentSetupPackInstallation, AgentSetupPackResourceMap

        opts = (options or InstallOptions()).normalized()
        plan = self.plan(db, catalog_key=catalog_key, slug=slug, options=opts)
        if not plan.ok:
            return InstallResult(installation_id=None, plan=plan, dry_run=opts.dry_run)

        if opts.dry_run:
            return InstallResult(installation_id=None, plan=plan, dry_run=True)

        pack = self.loader.load_pack(catalog_key=plan.catalog_key, slug=plan.pack_slug)
        installation = AgentSetupPackInstallation(
            template_key=plan.catalog_key,
            template_version=plan.version,
            status="pending",
            created_by_user_id=user_id,
            options_json=json.dumps(
                {
                    "alias_prefix": opts.alias_prefix,
                    "tool_profile": opts.tool_profile,
                    "flow_status": opts.flow_status,
                    "visibility": opts.visibility,
                    "pack_slug": plan.pack_slug,
                    "selection": self._selection_payload(opts.selection),
                },
                ensure_ascii=False,
            ),
        )
        db.add(installation)
        db.flush()

        created_agent_ids: list[int] = []
        created_deep_ids: list[int] = []
        created_flow_ids: list[int] = []
        installed: list[InstalledResource] = []
        logical_to_agent_id: dict[str, int] = {}

        try:
            alias_map = self._resolve_aliases_for_install(db, pack, opts)
            agents, deep_agents, flows = self._selected_templates(pack, opts.selection)

            for template in agents:
                alias = alias_map[template.logical_key]
                existing = db.query(Agent).filter(Agent.alias == alias).first()
                if existing and opts.on_alias_conflict == "skip":
                    logical_to_agent_id[template.logical_key] = existing.id
                    continue

                agent = self._create_regular_agent(
                    db, template, alias=alias, options=opts, user_id=user_id
                )
                logical_to_agent_id[template.logical_key] = agent.id
                created_agent_ids.append(agent.id)
                installed.append(
                    InstalledResource(
                        logical_key=template.logical_key,
                        resource_type="agent",
                        resource_id=agent.id,
                        alias=alias,
                    )
                )
                db.add(
                    AgentSetupPackResourceMap(
                        installation_id=installation.id,
                        logical_key=template.logical_key,
                        resource_type="agent",
                        resource_id=agent.id,
                        alias=alias,
                    )
                )

            for template in deep_agents:
                alias = alias_map[template.logical_key]
                existing = db.query(Agent).filter(Agent.alias == alias).first()
                if existing and opts.on_alias_conflict == "skip":
                    logical_to_agent_id[template.logical_key] = existing.id
                    continue

                sub_ids = self._resolve_sub_agent_ids(
                    db, pack, template, opts, alias_map, logical_to_agent_id
                )
                agent = self._create_deep_agent(
                    db,
                    template,
                    alias=alias,
                    sub_agent_ids=sub_ids,
                    options=opts,
                    user_id=user_id,
                )
                logical_to_agent_id[template.logical_key] = agent.id
                created_deep_ids.append(agent.id)
                installed.append(
                    InstalledResource(
                        logical_key=template.logical_key,
                        resource_type="deep_agent",
                        resource_id=agent.id,
                        alias=alias,
                    )
                )
                db.add(
                    AgentSetupPackResourceMap(
                        installation_id=installation.id,
                        logical_key=template.logical_key,
                        resource_type="deep_agent",
                        resource_id=agent.id,
                        alias=alias,
                    )
                )

            for template in flows:
                flow_json = rewrite_flow_agent_aliases(
                    template.flow,
                    target_prefix=opts.alias_prefix,
                    source_prefix=template.alias_prefix,
                )
                self._validate_flow_graph(flow_json)
                missing = self._missing_flow_agent_aliases(db, flow_json)
                if missing:
                    raise PackInstallerError(
                        "Install required agents first: " + ", ".join(missing)
                    )

                row = self._create_flow(
                    db,
                    template,
                    flow_json=flow_json,
                    options=opts,
                    user_id=user_id,
                )
                created_flow_ids.append(row.id)
                installed.append(
                    InstalledResource(
                        logical_key=template.logical_key,
                        resource_type="flow",
                        resource_id=row.id,
                        alias="",
                    )
                )
                db.add(
                    AgentSetupPackResourceMap(
                        installation_id=installation.id,
                        logical_key=template.logical_key,
                        resource_type="flow",
                        resource_id=row.id,
                        alias=None,
                    )
                )

            installation.status = "success"
            installation.created_agent_ids_json = json.dumps(created_agent_ids)
            installation.created_deep_agent_ids_json = json.dumps(created_deep_ids)
            installation.created_flow_ids_json = json.dumps(created_flow_ids)
            installation.error_message = None
            db.commit()
            db.refresh(installation)
            return InstallResult(
                installation_id=installation.id,
                plan=plan,
                resources=installed,
                dry_run=False,
            )
        except Exception as exc:
            db.rollback()
            installation.status = "failed"
            installation.error_message = str(exc)
            db.commit()
            plan.errors.append(str(exc))
            raise PackInstallerError(str(exc)) from exc

    def _validate_pack(self, pack: LoadedPack, plan: InstallPlan) -> None:
        if not pack.agents and not pack.deep_agents and not pack.flows:
            plan.errors.append(f"Pack '{pack.manifest.slug}' has no installable resources.")

        keys = [a.logical_key for a in pack.agents]
        if len(keys) != len(set(keys)):
            plan.errors.append("Duplicate logical_key in agents/.")

        deep_keys = [d.logical_key for d in pack.deep_agents]
        if len(deep_keys) != len(set(deep_keys)):
            plan.errors.append("Duplicate logical_key in deep_agents/.")

        overlap = set(keys) & set(deep_keys)
        if overlap:
            plan.errors.append(f"logical_key used for both agent and deep_agent: {sorted(overlap)}")

        if pack.deep_agents:
            try:
                from plugins.deep_agent_builder.models import DeepAgentSubAgent  # noqa: F401
            except ImportError:
                plan.warnings.append(
                    "deep_agent_builder plugin is not available; deep agent install may fail."
                )

        if pack.flows:
            try:
                from plugins.agent_flow.models import AgentFlowDefinition  # noqa: F401
            except ImportError:
                plan.errors.append("agent_flow plugin is required to install flows.")

    def _planned_aliases(self, pack: LoadedPack, opts: InstallOptions) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for template in pack.agents:
            mapping[template.logical_key] = build_alias(opts.alias_prefix, template.alias_suffix)
        for template in pack.deep_agents:
            mapping[template.logical_key] = build_alias(opts.alias_prefix, template.alias_suffix)
        return mapping

    def _resolve_aliases_for_install(
        self, db: Session, pack: LoadedPack, opts: InstallOptions
    ) -> dict[str, str]:
        if opts.on_alias_conflict != "suffix":
            return self._planned_aliases(pack, opts)

        mapping = self._planned_aliases(pack, opts)
        for logical_key, alias in list(mapping.items()):
            if db.query(Agent.id).filter(Agent.alias == alias).first() is None:
                continue
            suffix = 2
            while True:
                candidate = f"{alias}_{suffix}"
                if _ALIAS_PATTERN.fullmatch(candidate) and (
                    db.query(Agent.id).filter(Agent.alias == candidate).first() is None
                ):
                    mapping[logical_key] = candidate
                    break
                suffix += 1
                if suffix > 999:
                    raise PackInstallerError(f"Could not allocate free alias for '{alias}'.")
        return mapping

    @staticmethod
    def _selection_payload(selection: InstallSelection | None) -> dict[str, Any]:
        if selection is None or not selection.is_partial:
            return {"mode": "full"}
        return {
            "mode": "partial",
            "agents": sorted(selection.agents) if selection.agents is not None else None,
            "deep_agents": sorted(selection.deep_agents)
            if selection.deep_agents is not None
            else None,
            "flows": sorted(selection.flows) if selection.flows is not None else None,
        }

    @staticmethod
    def _selected_templates(
        pack: LoadedPack, selection: InstallSelection | None
    ) -> tuple[list[AgentTemplate], list[DeepAgentTemplate], list[FlowTemplate]]:
        sel = selection or InstallSelection.full_pack()
        if not sel.is_partial:
            return pack.agents, pack.deep_agents, pack.flows

        agents = (
            [a for a in pack.agents if a.logical_key in (sel.agents or set())]
            if sel.agents is not None
            else pack.agents
        )
        deep_agents = (
            [d for d in pack.deep_agents if d.logical_key in (sel.deep_agents or set())]
            if sel.deep_agents is not None
            else pack.deep_agents
        )
        flows = (
            [f for f in pack.flows if f.logical_key in (sel.flows or set())]
            if sel.flows is not None
            else pack.flows
        )
        return agents, deep_agents, flows

    def _missing_sub_agents_in_db(
        self,
        db: Session,
        pack: LoadedPack,
        template: DeepAgentTemplate,
        opts: InstallOptions,
        alias_map: dict[str, str],
        *,
        installing_keys: set[str] | None = None,
    ) -> list[str]:
        missing: list[str] = []
        agents_by_key = {a.logical_key: a for a in pack.agents}
        pending = installing_keys or set()
        for key in template.sub_agent_logical_keys:
            if key in pending:
                continue
            agent_t = agents_by_key.get(key)
            if agent_t is None:
                continue
            alias = alias_map.get(key) or build_alias(opts.alias_prefix, agent_t.alias_suffix)
            if db.query(Agent.id).filter(Agent.alias == alias).first() is None:
                missing.append(f"{key} ({alias})")
        return missing

    def _resolve_sub_agent_ids(
        self,
        db: Session,
        pack: LoadedPack,
        template: DeepAgentTemplate,
        opts: InstallOptions,
        alias_map: dict[str, str],
        logical_to_agent_id: dict[str, int],
    ) -> list[int]:
        sub_ids: list[int] = []
        missing: list[str] = []
        agents_by_key = {a.logical_key: a for a in pack.agents}
        for key in template.sub_agent_logical_keys:
            if key in logical_to_agent_id:
                sub_ids.append(logical_to_agent_id[key])
                continue
            agent_t = agents_by_key.get(key)
            if agent_t is None:
                missing.append(key)
                continue
            alias = alias_map.get(key) or build_alias(opts.alias_prefix, agent_t.alias_suffix)
            row = db.query(Agent).filter(Agent.alias == alias).first()
            if row is None:
                missing.append(f"{key} ({alias})")
                continue
            logical_to_agent_id[key] = row.id
            sub_ids.append(row.id)
        if missing:
            raise PackInstallerError(
                "Install required sub-agents first: " + ", ".join(missing)
            )
        return sub_ids

    @staticmethod
    def _missing_flow_agent_aliases(db: Session, flow_json: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for node in flow_json.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            if str(node.get("type") or "agent").strip().lower() != "agent":
                continue
            alias = str(node.get("agent_alias") or "").strip()
            if not alias:
                continue
            if db.query(Agent.id).filter(Agent.alias == alias).first() is None:
                missing.append(alias)
        return missing

    def _validate_flow_templates(
        self, pack: LoadedPack, plan: InstallPlan, opts: InstallOptions
    ) -> None:
        _, _, flows = self._selected_templates(pack, opts.selection)
        for template in flows:
            try:
                flow_json = rewrite_flow_agent_aliases(
                    template.flow,
                    target_prefix=opts.alias_prefix,
                    source_prefix=template.alias_prefix,
                )
                self._validate_flow_graph(flow_json)
            except Exception as exc:
                plan.errors.append(f"Flow '{template.logical_key}': {exc}")

    def _alias_action(self, db: Session, alias: str, opts: InstallOptions) -> str:
        exists = db.query(Agent.id).filter(Agent.alias == alias).first() is not None
        if not exists:
            return "create"
        if opts.on_alias_conflict == "skip":
            return "skip"
        if opts.on_alias_conflict == "suffix":
            return "create_with_suffix"
        return "conflict"

    @staticmethod
    def _agent_name(template: AgentTemplate | DeepAgentTemplate) -> str:
        agent_meta = template.data.get("agent") or {}
        return str(agent_meta.get("name") or template.logical_key).strip()

    def _create_regular_agent(
        self,
        db: Session,
        template: AgentTemplate,
        *,
        alias: str,
        options: InstallOptions,
        user_id: str | None,
    ) -> Agent:
        meta = template.data.get("agent") or {}
        tags = self._merge_tags(template.data.get("tags"), options.extra_tags)

        agent = Agent(
            name=str(meta.get("name") or template.logical_key).strip(),
            description=(meta.get("description") or None),
            alias=alias,
            tags=tags,
            status=str(meta.get("status") or "active").strip(),
            created_by_user_id=user_id,
        )
        db.add(agent)
        db.flush()

        self._attach_agent_children(db, agent.id, template.data, options)
        return agent

    def _create_deep_agent(
        self,
        db: Session,
        template: DeepAgentTemplate,
        *,
        alias: str,
        sub_agent_ids: list[int],
        options: InstallOptions,
        user_id: str | None,
    ) -> Agent:
        from plugins.deep_agent_builder.models import DeepAgentSubAgent

        meta = template.data.get("agent") or {}
        tags = self._merge_tags(template.data.get("tags"), options.extra_tags)

        agent = Agent(
            name=str(meta.get("name") or template.logical_key).strip(),
            description=(meta.get("description") or None),
            alias=alias,
            tags=tags,
            status=str(meta.get("status") or "active").strip(),
            created_by_user_id=user_id,
        )
        db.add(agent)
        db.flush()

        if hasattr(agent, "is_deep"):
            agent.is_deep = bool(meta.get("is_deep", True))
        if hasattr(agent, "is_async_subagents"):
            agent.is_async_subagents = bool(meta.get("is_async_subagents", True))

        self._attach_agent_children(db, agent.id, template.data, options)

        for sub_id in sub_agent_ids:
            db.add(DeepAgentSubAgent(deep_agent_id=agent.id, sub_agent_id=sub_id))
        db.flush()
        return agent

    def _attach_agent_children(
        self,
        db: Session,
        agent_id: int,
        data: dict[str, Any],
        options: InstallOptions,
    ) -> None:
        prompts = data.get("prompts") or {}
        if isinstance(prompts, dict):
            for key, value in prompts.items():
                if key and value is not None:
                    db.add(
                        AgentPrompt(
                            agent_id=agent_id,
                            key=str(key).strip(),
                            value=str(value),
                        )
                    )

        settings = data.get("settings") or {}
        if isinstance(settings, dict):
            for key, value in settings.items():
                if key:
                    db.add(
                        AgentSetting(
                            agent_id=agent_id,
                            key=str(key).strip(),
                            value=str(value or ""),
                        )
                    )

        for skill in data.get("skills") or []:
            if not isinstance(skill, dict) or not skill.get("name"):
                continue
            raw_tags = skill.get("tags")
            if isinstance(raw_tags, list):
                tag_str = ",".join(str(t).strip() for t in raw_tags if str(t).strip())
            else:
                tag_str = str(raw_tags or "")
            skill_kwargs: dict[str, Any] = {
                "agent_id": agent_id,
                "name": str(skill["name"]).strip(),
                "description": str(skill.get("description") or ""),
                "content": str(skill.get("content") or ""),
                "status": str(skill.get("status") or "enabled").strip(),
            }
            if hasattr(AgentSkill, "tags"):
                skill_kwargs["tags"] = normalize_skill_tags(tag_str)
            db.add(AgentSkill(**skill_kwargs))

        tool_cfg = apply_tool_profile(data.get("tool_config"), options.tool_profile)
        db.add(
            AgentToolConfig(
                agent_id=agent_id,
                config_json=tool_config_to_json(tool_cfg),
            )
        )

        policy = data.get("tool_policy") or {}
        if isinstance(policy, dict) and policy:
            db.add(
                AgentToolPolicyConfig(
                    agent_id=agent_id,
                    config_json=json.dumps(policy, ensure_ascii=False),
                )
            )

        limits = data.get("tool_limits") or {}
        if isinstance(limits, dict) and limits:
            db.add(
                AgentToolLimitConfig(
                    agent_id=agent_id,
                    config_json=json.dumps(limits, ensure_ascii=False),
                )
            )

    @staticmethod
    def _merge_tags(pack_tags: Any, extra: list[str]) -> str | None:
        items: list[str] = []
        seen: set[str] = set()
        if isinstance(pack_tags, list):
            source = pack_tags
        elif isinstance(pack_tags, str):
            source = pack_tags.split(",")
        else:
            source = []
        for piece in list(source) + list(extra):
            tag = str(piece).strip().lower()
            if tag and tag not in seen:
                seen.add(tag)
                items.append(tag)
        return ",".join(items) if items else None

    @staticmethod
    def _create_flow(
        db: Session,
        template: FlowTemplate,
        *,
        flow_json: dict[str, Any],
        options: InstallOptions,
        user_id: str | None,
    ):
        from plugins.agent_flow.models import AgentFlowDefinition

        status = options.flow_status or template.status or "draft"
        row = AgentFlowDefinition(
            name=template.name,
            description=template.description,
            status=status,
            flow_json=json.dumps(flow_json, ensure_ascii=False),
            created_by_user_id=user_id,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def _validate_flow_graph(flow_json: dict[str, Any]) -> None:
        from plugins.agent_flow.services.agent_flow_factory import AgentFlowFactory

        factory = AgentFlowFactory(flow_json)
        factory._validate_graph()
        factory._topological_order()
