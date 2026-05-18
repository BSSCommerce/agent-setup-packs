# delivery_core pack — internal notes

Pack folder: `delivery_core/`  
Catalog key: `engineering_delivery_core` (`pack_catalog.py`)

## Status

| Resource | Status |
|----------|--------|
| Regular agents (7) | Done — `delivery_core/agents/*.yaml` |
| Deep agents (1) | Done — `delivery_core/deep_agents/feature_delivery_lead.yaml` |
| Flows (3) | Done — `delivery_core/flows/*.json` |

## Open issues

### Installer

- Generic installer: `services/pack_installer.py` (dry-run + install API on pack detail page).
- Requires plugins: `agent_flow` (flows), `deep_agent_builder` (deep agents + `is_deep` columns).
- **Alias convention:** `{alias_prefix}_{alias_suffix}` with default prefix `it` (see `alias_prefix` in flow JSON and `alias_suffix` in agent YAML).
- **Flows:** Installer must rewrite `agent_alias` values when admin chooses a non-`it` prefix.
- **Deep agent:** Map `sub_agents` logical keys to installed regular agent IDs in `plugin_deep_agent_sub_agents`.

### Tool policy

- Human approval required for Jira, GitLab, CLI, browser writes, etc. when the **integrated** tool profile is used.
- Runtime policy keys are per-tool stable keys (`factory:{factory_key}:{tool_name}`).
- **TODO (installer):** Expand factory-level policy when enabling integrated tools.

### Missing / optional tools

| Tool factory key | Agents that reference it | Notes |
|------------------|--------------------------|-------|
| `enable_query_codebase_tools` | Solution Architect, Code Reviewer | Optional; off in read-only profile |
| `enable_jira_tools` | Product Requirements Analyst, QA, Release Manager | Requires Jira plugin |
| `enable_gitlab_tools` | Solution Architect, Backend, Code Reviewer, Release Manager | Requires GitLab plugin |
| `enable_google_drive_tools` | Product Requirements Analyst | Optional |
| `enable_browser_tools` | Frontend Engineer, QA Test Planner | Playwright; opt-in |
| `enable_cursor_cli_tool` / `enable_claude_cli_tool` | Backend, Frontend | Strict approval if enabled |

### Cross-pack / flow gaps

| Flow | Gap | Mitigation in pack |
|------|-----|-------------------|
| Feature Intake To Delivery Plan | No Security Review Lead node | `optional_nodes` in JSON; QA → Release direct |
| PR Review Readiness | No Security Review Lead node | Same; architect → qa → review → release |
| Bug Triage To Fix Plan | No Ticket Triage Agent | Uses `product_requirements_analyst` (`substitutions` in JSON) |

Installer may insert security-pack nodes when `security_compliance` is installed (see `optional_nodes` in flow files).

### Naming

- Research list "Release Notes Writer" vs catalog **Release Manager** — pack uses Release Manager.

## Pack inventory

### Regular agents

| logical_key | File |
|-------------|------|
| `product_requirements_analyst` | `agents/product_requirements_analyst.yaml` |
| `solution_architect` | `agents/solution_architect.yaml` |
| `backend_engineer` | `agents/backend_engineer.yaml` |
| `frontend_engineer` | `agents/frontend_engineer.yaml` |
| `qa_test_planner` | `agents/qa_test_planner.yaml` |
| `code_reviewer` | `agents/code_reviewer.yaml` |
| `release_manager` | `agents/release_manager.yaml` |

### Deep agent

| logical_key | File | Sub-agents |
|-------------|------|------------|
| `feature_delivery_lead` | `deep_agents/feature_delivery_lead.yaml` | All 7 regular agents above; `is_async_subagents: true` |

### Flows

| logical_key | File | Default aliases (`it_` prefix) |
|-------------|------|--------------------------------|
| `feature_intake_to_delivery_plan` | `flows/feature_intake_to_delivery_plan.json` | 7 agent nodes + 1 merge |
| `bug_triage_to_fix_plan` | `flows/bug_triage_to_fix_plan.json` | 6 agent nodes + 1 merge |
| `pr_review_readiness` | `flows/pr_review_readiness.json` | 4 agent nodes (linear) |

## Schema notes

- **Agent YAML:** `logical_key`, `alias_suffix`, `agent`, `prompts`, `skills`, `tool_config`, `output_contract`.
- **Deep agent YAML:** adds `sub_agents` (logical keys), `agent.is_deep`, `agent.is_async_subagents`.
- **Flow JSON:** wrapper metadata + `flow` object with `nodes`, `edges`, `start_node_id` (AgentFlowFactory shape).
