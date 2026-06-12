"""Agent Setup Packs community plugin."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

from core.plugin_sdk.base import MenuItem, PluginBase, PluginMeta

_PLUGIN_ROOT = Path(__file__).resolve().parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from models import AgentSetupPackInstallation, AgentSetupPackResourceMap  # noqa: E402
from router import router  # noqa: E402


class AgentSetupPacksPlugin(PluginBase):
    def meta(self) -> PluginMeta:
        return PluginMeta(
            name="agent_setup_packs",
            version="1.0.0 (beta)",
            description=(
                "IT company agent template packs — install Agents, DeepAgents, "
                "and AgentFlows from versioned on-disk pack definitions."
            ),
            author="ai-department",
        )

    def models(self):
        return [AgentSetupPackInstallation, AgentSetupPackResourceMap]

    def routers(self) -> list[APIRouter]:
        return [router]

    def menu_items(self) -> list[MenuItem]:
        return [
            MenuItem(
                label="Setup Packs",
                url="/agent-setup-packs",
                icon="package",
                order=18,
                key="agent_setup_packs",
                parent_key="multi_agents",
            ),
        ]
