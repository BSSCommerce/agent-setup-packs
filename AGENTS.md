# Agent Setup Packs — agent context

Community plugin (`agent_setup_packs`) that provisions **IT company template packs**: regular **Agents**, **DeepAgents**, and **AgentFlows** from declarative files. UI: `/agent-setup-packs` (overview + per-pack detail). Generic installer: `services/pack_loader.py`, `services/pack_installer.py`. DB: `AgentSetupPackInstallation`, `AgentSetupPackResourceMap`.

## Plugin root (code)

| Path | Role |
|------|------|
| `plugin.py` | `PluginBase` registration, menu under Multi Agents |
| `router.py` | Overview and pack detail pages |
| `pack_catalog.py` | Static pack metadata for UI (names, counts, layers); `pack_slug` → on-disk folder |
| `services/pack_loader.py` | Discover/load `pack.yaml`, agents, deep_agents, flows |
| `services/pack_installer.py` | Dry-run and install into core DB |
| `models.py` | Installation + resource map tables |
| `templates/` | Jinja pages extending `base.html` |

Enable via `PLUGINS_EXTERNAL_DIR=community_plugins` and turn on plugin **agent_setup_packs** in admin.

## Pack content layout (important)

**Each pack lives in its own folder** under this plugin directory. Do not mix packs in one tree.

Each pack folder has **exactly three subfolders** — one primitive type per folder:

```text
<pack_slug>/
├── agents/        # Single Agent definitions (prompts, skills, tools, settings)
├── deep_agents/   # DeepAgent definitions + sub-agent references
└── flows/         # AgentFlow DAG definitions (flow_json, node → agent_alias)
```

The installer (when implemented) should read a pack folder, create `core_agents` rows from `agents/` and `deep_agents/`, then create `plugin_agent_flow_definitions` from `flows/` using resolved aliases.

### Example: `core_delivery/`

Maps to catalog pack **Engineering Delivery Core** (`engineering_delivery_core` in `pack_catalog.py`).

```text
core_delivery/
├── agents/          # e.g. product_requirements_analyst.yaml, backend_engineer.yaml
├── deep_agents/     # e.g. feature_delivery_lead.yaml (lists sub-agent logical keys)
└── flows/           # e.g. feature_intake_to_delivery_plan.json
```

- **`agents/`** — one file per role agent; maps to `Agent`, `AgentPrompt`, `AgentSkill`, `AgentToolConfig`, etc.
- **`deep_agents/`** — one file per coordinator; `is_deep=True`, `sub_agents` point at aliases defined under `agents/`.
- **`flows/`** — one file per workflow; `nodes` / `edges` / `agent_alias` must match agents created from the same pack (optionally with a shared alias prefix at install time).

Add new packs by creating a sibling folder (same 3-subfolder shape) and registering metadata in `pack_catalog.py`.

## Conventions for coding agents

- Keep pack folder names **short slugs** (`core_delivery`, `devops_sre`, …); catalog `key` may differ — document the mapping in `pack_catalog.py`.
- Prefer portable, versioned config files (YAML/JSON) over hard-coding manifests only in Python.
- Do not start PM2 / agent APIs from the installer unless explicitly requested.
- Match existing Agent Manager patterns: `core.database.base.Base`, plugin table prefix `plugin_agent_setup_pack_*`, English strings only.
