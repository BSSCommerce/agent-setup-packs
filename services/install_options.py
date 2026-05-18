"""Installation options shared by dry-run and install."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InstallSelection:
    """Subset of pack resources to install. ``None`` on a field means all of that type."""

    agents: set[str] | None = None
    deep_agents: set[str] | None = None
    flows: set[str] | None = None

    @classmethod
    def full_pack(cls) -> InstallSelection:
        return cls()

    @classmethod
    def single(cls, resource_type: str, logical_key: str) -> InstallSelection:
        key = (logical_key or "").strip()
        rtype = (resource_type or "").strip().lower()
        if not key or rtype not in {"agent", "deep_agent", "flow"}:
            raise ValueError("resource_type and logical_key are required for single install.")
        empty: set[str] = set()
        if rtype == "agent":
            return cls(agents={key}, deep_agents=empty, flows=empty)
        if rtype == "deep_agent":
            return cls(agents=empty, deep_agents={key}, flows=empty)
        return cls(agents=empty, deep_agents=empty, flows={key})

    @property
    def is_partial(self) -> bool:
        return self.agents is not None or self.deep_agents is not None or self.flows is not None


@dataclass
class InstallOptions:
    """User-selected options when installing a setup pack."""

    alias_prefix: str = "it"
    tool_profile: str = "read_only"
    flow_status: str = "draft"
    visibility: str = "creator"
    dry_run: bool = False
    on_alias_conflict: str = "fail"
    extra_tags: list[str] = field(default_factory=list)
    selection: InstallSelection | None = None

    def normalized(self) -> InstallOptions:
        prefix = (self.alias_prefix or "it").strip().lower()
        prefix = prefix.rstrip("_")
        profile = (self.tool_profile or "read_only").strip().lower()
        if profile not in {"prompt_only", "read_only", "integrated"}:
            profile = "read_only"
        flow_status = (self.flow_status or "draft").strip().lower()
        if flow_status not in {"draft", "active", "archived"}:
            flow_status = "draft"
        visibility = (self.visibility or "creator").strip().lower()
        if visibility not in {"creator", "all_admins"}:
            visibility = "creator"
        conflict = (self.on_alias_conflict or "fail").strip().lower()
        if conflict not in {"fail", "skip", "suffix"}:
            conflict = "fail"
        tags = [t.strip().lower() for t in self.extra_tags if t and str(t).strip()]
        selection = self.selection if self.selection is not None else InstallSelection.full_pack()
        return InstallOptions(
            alias_prefix=prefix,
            tool_profile=profile,
            flow_status=flow_status,
            visibility=visibility,
            dry_run=self.dry_run,
            on_alias_conflict=conflict,
            extra_tags=tags,
            selection=selection,
        )
