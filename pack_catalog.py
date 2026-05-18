"""Static catalog of IT company setup packs (presentation + future installer)."""

from __future__ import annotations

from typing import Any, TypedDict


class PackStats(TypedDict):
    agents: int
    deep_agents: int
    flows: int


class SetupPack(TypedDict):
    key: str
    pack_slug: str
    name: str
    short_name: str
    org_layer: str
    org_layer_order: int
    metaphor: str
    metaphor_icon: str
    accent: str
    audience: str
    summary: str
    recommended: bool
    stats: PackStats
    agents: list[str]
    deep_agents: list[str]
    flows: list[str]
    primitives: list[str]


SETUP_PACKS: list[SetupPack] = [
    {
        "key": "engineering_delivery_core",
        "pack_slug": "delivery_core",
        "name": "Engineering Delivery Core",
        "short_name": "Engineering",
        "org_layer": "Core Delivery",
        "org_layer_order": 3,
        "metaphor": "Assembly line",
        "metaphor_icon": "layers",
        "accent": "indigo",
        "audience": "Product, engineering, and delivery teams",
        "summary": (
            "Turn ideas into shippable software: requirements, architecture, "
            "implementation planning, QA, and release readiness."
        ),
        "recommended": True,
        "stats": {"agents": 7, "deep_agents": 1, "flows": 3},
        "agents": [
            "Product Requirements Analyst",
            "Solution Architect",
            "Backend Engineer",
            "Frontend Engineer",
            "QA Test Planner",
            "Code Reviewer",
            "Release Manager",
        ],
        "deep_agents": ["Feature Delivery Lead"],
        "flows": [
            "Feature Intake To Delivery Plan",
            "Bug Triage To Fix Plan",
            "PR Review Readiness",
        ],
        "primitives": ["Agent", "DeepAgent", "AgentFlow"],
    },
    {
        "key": "devops_sre_operations",
        "pack_slug": "devops_sre",
        "name": "DevOps & SRE Operations",
        "short_name": "Platform",
        "org_layer": "Reliability & Operations",
        "org_layer_order": 4,
        "metaphor": "Control tower",
        "metaphor_icon": "activity",
        "accent": "amber",
        "audience": "DevOps, platform, and SRE teams",
        "summary": (
            "Investigate incidents, assess change risk, execute runbooks, "
            "and produce post-incident reviews with human approval gates."
        ),
        "recommended": True,
        "stats": {"agents": 5, "deep_agents": 1, "flows": 3},
        "agents": [
            "Incident Triage Analyst",
            "Logs & Metrics Investigator",
            "Runbook Executor",
            "Change Risk Analyst",
            "Post-Incident Review Writer",
        ],
        "deep_agents": ["Incident Commander"],
        "flows": [
            "Incident Response",
            "Change Request Review",
            "Post-Incident Review",
        ],
        "primitives": ["Agent", "DeepAgent", "AgentFlow"],
    },
    {
        "key": "security_compliance",
        "pack_slug": "security_compliance",
        "name": "Security & Compliance",
        "short_name": "Security",
        "org_layer": "Trust & Governance",
        "org_layer_order": 5,
        "metaphor": "Shield wall",
        "metaphor_icon": "shield",
        "accent": "rose",
        "audience": "AppSec, SecOps, compliance, and engineering governance",
        "summary": (
            "Threat modeling, vulnerability triage, access reviews, and "
            "compliance evidence — recommendations first, remediation gated."
        ),
        "recommended": False,
        "stats": {"agents": 5, "deep_agents": 1, "flows": 3},
        "agents": [
            "Threat Modeling Analyst",
            "Dependency Vulnerability Analyst",
            "Access Review Analyst",
            "Security Policy Reviewer",
            "Compliance Evidence Collector",
        ],
        "deep_agents": ["Security Review Lead"],
        "flows": [
            "Security Review Gate",
            "Vulnerability Intake To Remediation",
            "Compliance Evidence Request",
        ],
        "primitives": ["Agent", "DeepAgent", "AgentFlow"],
    },
    {
        "key": "it_service_desk",
        "pack_slug": "it_service_desk",
        "name": "IT Service Desk",
        "short_name": "Service Desk",
        "org_layer": "Employee Services",
        "org_layer_order": 6,
        "metaphor": "Help desk",
        "metaphor_icon": "headphones",
        "accent": "emerald",
        "audience": "Internal IT, help desk, and ITSM teams",
        "summary": (
            "ITIL-aligned ticket triage, knowledge search, access requests, "
            "and SLA-aware escalation for employee support."
        ),
        "recommended": False,
        "stats": {"agents": 5, "deep_agents": 1, "flows": 3},
        "agents": [
            "Ticket Triage Agent",
            "Knowledge Base Search Agent",
            "Access Request Analyst",
            "Hardware & Software Support Agent",
            "SLA Escalation Agent",
        ],
        "deep_agents": ["Service Desk Coordinator"],
        "flows": [
            "Ticket Triage And Resolution",
            "Access Request Review",
            "Knowledge Article Creation",
        ],
        "primitives": ["Agent", "DeepAgent", "AgentFlow"],
    },
    {
        "key": "data_analytics",
        "pack_slug": "data_analytics",
        "name": "Data & Analytics",
        "short_name": "Data",
        "org_layer": "Business Intelligence",
        "org_layer_order": 2,
        "metaphor": "Observatory",
        "metaphor_icon": "chart",
        "accent": "violet",
        "audience": "Data analysts, BI, data engineering, and product analytics",
        "summary": (
            "Clarify metrics, draft query plans, validate data quality, "
            "and narrate insights with strict gates on sensitive queries."
        ),
        "recommended": False,
        "stats": {"agents": 5, "deep_agents": 1, "flows": 3},
        "agents": [
            "Data Request Clarifier",
            "SQL Analyst",
            "Data Quality Validator",
            "Dashboard Specification Writer",
            "Insight Narrator",
        ],
        "deep_agents": ["Data Analysis Lead"],
        "flows": [
            "Business Data Request",
            "Data Quality Investigation",
            "Metrics Definition Review",
        ],
        "primitives": ["Agent", "DeepAgent", "AgentFlow"],
    },
    {
        "key": "customer_technical_support",
        "pack_slug": "customer_technical_support",
        "name": "Customer Technical Support",
        "short_name": "Customer Success",
        "org_layer": "Customer Experience",
        "org_layer_order": 1,
        "metaphor": "Bridge",
        "metaphor_icon": "users",
        "accent": "sky",
        "audience": "B2B support, solution engineering, and customer success",
        "summary": (
            "Summarize customer issues, search knowledge, draft engineering "
            "escalations, and separate internal diagnosis from external replies."
        ),
        "recommended": False,
        "stats": {"agents": 5, "deep_agents": 1, "flows": 3},
        "agents": [
            "Customer Issue Summarizer",
            "Reproduction Guide Writer",
            "Support Knowledge Search Agent",
            "Engineering Escalation Drafter",
            "Customer Response Writer",
        ],
        "deep_agents": ["Technical Support Lead"],
        "flows": [
            "Customer Ticket To Engineering Escalation",
            "Support Response Draft",
            "Known Issue Article Draft",
        ],
        "primitives": ["Agent", "DeepAgent", "AgentFlow"],
    },
]

ORG_LAYERS: list[dict[str, Any]] = [
    {
        "order": 0,
        "name": "Control Plane",
        "description": "Agent Manager orchestrates agents, flows, and policies.",
        "metaphor": "Company HQ",
    },
    {
        "order": 1,
        "name": "Customer Experience",
        "description": "Outward-facing support and success workflows.",
        "metaphor": "Front office",
    },
    {
        "order": 2,
        "name": "Business Intelligence",
        "description": "Metrics, analytics, and decision support.",
        "metaphor": "Observatory",
    },
    {
        "order": 3,
        "name": "Core Delivery",
        "description": "Software product design, build, and release.",
        "metaphor": "Factory floor",
    },
    {
        "order": 4,
        "name": "Reliability & Operations",
        "description": "Incidents, changes, and production stability.",
        "metaphor": "Control tower",
    },
    {
        "order": 5,
        "name": "Trust & Governance",
        "description": "Security, risk, and compliance assurance.",
        "metaphor": "Shield wall",
    },
    {
        "order": 6,
        "name": "Employee Services",
        "description": "Internal IT support and employee enablement.",
        "metaphor": "Help desk",
    },
]

PRIMITIVE_LEGEND: list[dict[str, str]] = [
    {
        "name": "Agent",
        "metaphor": "Specialist",
        "description": "A focused role with prompts, skills, and optional tools.",
        "color": "sky",
    },
    {
        "name": "DeepAgent",
        "metaphor": "Team lead",
        "description": "Coordinates sub-agents inside one department boundary.",
        "color": "violet",
    },
    {
        "name": "AgentFlow",
        "metaphor": "Assembly line",
        "description": "Repeatable DAG workflow with approval and resume support.",
        "color": "emerald",
    },
]


def get_pack_by_key(key: str) -> SetupPack | None:
    for pack in SETUP_PACKS:
        if pack["key"] == key:
            return pack
    return None


def get_pack_slug_for_key(catalog_key: str) -> str | None:
    pack = get_pack_by_key(catalog_key)
    if pack is None:
        return None
    return str(pack.get("pack_slug") or "").strip() or None


def catalog_totals() -> dict[str, int]:
    return {
        "pack_count": len(SETUP_PACKS),
        "agent_count": sum(p["stats"]["agents"] for p in SETUP_PACKS),
        "deep_agent_count": sum(p["stats"]["deep_agents"] for p in SETUP_PACKS),
        "flow_count": sum(p["stats"]["flows"] for p in SETUP_PACKS),
    }
