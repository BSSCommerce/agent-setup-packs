"""Load setup pack definitions from disk (any pack folder with pack.yaml)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent


class PackNotFoundError(LookupError):
    """Raised when a pack slug or catalog key cannot be resolved."""


@dataclass(frozen=True)
class PackManifest:
    slug: str
    version: str
    catalog_key: str
    name: str
    description: str
    root: Path

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def deep_agents_dir(self) -> Path:
        return self.root / "deep_agents"

    @property
    def flows_dir(self) -> Path:
        return self.root / "flows"


@dataclass
class AgentTemplate:
    logical_key: str
    alias_suffix: str
    data: dict[str, Any]
    source_path: Path


@dataclass
class DeepAgentTemplate:
    logical_key: str
    alias_suffix: str
    sub_agent_logical_keys: list[str]
    data: dict[str, Any]
    source_path: Path


@dataclass
class FlowTemplate:
    logical_key: str
    name: str
    description: str
    status: str
    alias_prefix: str
    flow: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None


@dataclass
class LoadedPack:
    manifest: PackManifest
    agents: list[AgentTemplate]
    deep_agents: list[DeepAgentTemplate]
    flows: list[FlowTemplate]


def plugin_root() -> Path:
    return _PLUGIN_ROOT


def discover_pack_slugs(root: Path | None = None) -> list[str]:
    """Return folder names under plugin root that contain pack.yaml."""
    base = root or plugin_root()
    slugs: list[str] = []
    if not base.is_dir():
        return slugs
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if (child / "pack.yaml").is_file():
            slugs.append(child.name)
    return slugs


def load_pack_manifest(slug: str, root: Path | None = None) -> PackManifest:
    base = root or plugin_root()
    pack_dir = base / slug
    manifest_path = pack_dir / "pack.yaml"
    if not manifest_path.is_file():
        raise PackNotFoundError(f"Pack '{slug}' not found (missing pack.yaml).")

    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    catalog_key = str(raw.get("catalog_key") or "").strip()
    if not catalog_key:
        raise PackNotFoundError(f"Pack '{slug}' is missing catalog_key in pack.yaml.")

    return PackManifest(
        slug=slug,
        version=str(raw.get("version") or "0.1.0").strip(),
        catalog_key=catalog_key,
        name=str(raw.get("name") or slug).strip(),
        description=str(raw.get("description") or "").strip(),
        root=pack_dir,
    )


def resolve_pack_slug(
    *,
    catalog_key: str | None = None,
    slug: str | None = None,
    root: Path | None = None,
) -> str:
    """Resolve pack folder slug from catalog_key or explicit slug."""
    if slug:
        slug = slug.strip()
        load_pack_manifest(slug, root=root)
        return slug

    key = (catalog_key or "").strip()
    if not key:
        raise PackNotFoundError("catalog_key or slug is required.")

    for candidate in discover_pack_slugs(root):
        manifest = load_pack_manifest(candidate, root=root)
        if manifest.catalog_key == key:
            return candidate

    raise PackNotFoundError(f"No pack folder found for catalog_key '{key}'.")


class PackLoader:
    """Loads pack manifests and declarative resources from disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or plugin_root()

    def discover_slugs(self) -> list[str]:
        return discover_pack_slugs(self.root)

    def load_manifest(self, slug: str) -> PackManifest:
        return load_pack_manifest(slug, root=self.root)

    def load_pack(self, *, catalog_key: str | None = None, slug: str | None = None) -> LoadedPack:
        resolved_slug = resolve_pack_slug(catalog_key=catalog_key, slug=slug, root=self.root)
        manifest = load_pack_manifest(resolved_slug, root=self.root)
        return LoadedPack(
            manifest=manifest,
            agents=self._load_agents(manifest),
            deep_agents=self._load_deep_agents(manifest),
            flows=self._load_flows(manifest),
        )

    def _load_agents(self, manifest: PackManifest) -> list[AgentTemplate]:
        agents_dir = manifest.agents_dir
        if not agents_dir.is_dir():
            return []

        templates: list[AgentTemplate] = []
        for path in sorted(agents_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            logical_key = str(data.get("logical_key") or path.stem).strip()
            alias_suffix = str(data.get("alias_suffix") or logical_key).strip()
            templates.append(
                AgentTemplate(
                    logical_key=logical_key,
                    alias_suffix=alias_suffix,
                    data=data,
                    source_path=path,
                )
            )
        return templates

    def _load_deep_agents(self, manifest: PackManifest) -> list[DeepAgentTemplate]:
        deep_dir = manifest.deep_agents_dir
        if not deep_dir.is_dir():
            return []

        templates: list[DeepAgentTemplate] = []
        for path in sorted(deep_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            logical_key = str(data.get("logical_key") or path.stem).strip()
            alias_suffix = str(data.get("alias_suffix") or logical_key).strip()
            raw_subs = data.get("sub_agents") or []
            sub_keys: list[str] = []
            for item in raw_subs:
                if isinstance(item, str):
                    sub_keys.append(item.strip())
                elif isinstance(item, dict) and item.get("logical_key"):
                    sub_keys.append(str(item["logical_key"]).strip())
            templates.append(
                DeepAgentTemplate(
                    logical_key=logical_key,
                    alias_suffix=alias_suffix,
                    sub_agent_logical_keys=[k for k in sub_keys if k],
                    data=data,
                    source_path=path,
                )
            )
        return templates

    def _load_flows(self, manifest: PackManifest) -> list[FlowTemplate]:
        flows_dir = manifest.flows_dir
        if not flows_dir.is_dir():
            return []

        templates: list[FlowTemplate] = []
        for path in sorted(flows_dir.glob("*.json")):
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            logical_key = str(wrapper.get("logical_key") or path.stem).strip()
            flow_body = wrapper.get("flow") or {}
            if not isinstance(flow_body, dict):
                raise ValueError(f"Flow '{path.name}' must contain a 'flow' object.")

            metadata = {
                k: v
                for k, v in wrapper.items()
                if k not in {"flow", "logical_key", "name", "description", "status", "alias_prefix"}
            }
            templates.append(
                FlowTemplate(
                    logical_key=logical_key,
                    name=str(wrapper.get("name") or logical_key).strip(),
                    description=str(wrapper.get("description") or "").strip(),
                    status=str(wrapper.get("status") or "draft").strip().lower(),
                    alias_prefix=str(wrapper.get("alias_prefix") or "it")
                    .strip()
                    .lower()
                    .rstrip("_"),
                    flow=flow_body,
                    metadata=metadata,
                    source_path=path,
                )
            )
        return templates
