from __future__ import annotations

from goskills.group_graph import CANDIDATE_POOL_CAP, MAX_GROUP_SIZE, build_group_graph
from goskills.retrieval import MAX_BACKFILL_SKILLS, MAX_SELECTED_GROUPS, retrieve


def sample_bundle() -> dict:
    return {
        "metadata": {"name": "unit"},
        "skills": [
            {
                "name": "xlsx-recovery",
                "description": "Recover missing Excel workbook cells and preserve xlsx formulas.",
                "inputs": ["incomplete xlsx workbook"],
                "outputs": ["recovered xlsx workbook"],
                "source_path": "/opt/goskills/skills/xlsx-recovery/SKILL.md",
                "rendered_snippet": "Use openpyxl to recover cells and formulas.",
            },
            {
                "name": "schema-verifier",
                "description": "Validate outputs with expected schema, row counts, and regression tests.",
                "inputs": ["candidate output"],
                "outputs": ["test report"],
                "source_path": "/opt/goskills/skills/schema-verifier/SKILL.md",
                "rendered_snippet": "Run verifier tests and compare expected artifacts.",
            },
            {
                "name": "pdf-extract",
                "description": "Extract tables from PDF documents into structured data.",
                "inputs": ["pdf"],
                "outputs": ["csv json"],
                "source_path": "/opt/goskills/skills/pdf-extract/SKILL.md",
            },
            {
                "name": "java-csv-pipeline",
                "description": "Build Java CSV transformation pipeline.",
                "inputs": ["csv"],
                "outputs": ["csv"],
                "source_path": "/opt/goskills/skills/java-csv-pipeline/SKILL.md",
            },
            {
                "name": "python-csv-pipeline",
                "description": "Build Python CSV transformation pipeline.",
                "inputs": ["csv"],
                "outputs": ["csv"],
                "source_path": "/opt/goskills/skills/python-csv-pipeline/SKILL.md",
            },
        ],
        "edges": [
            {
                "source": "xlsx-recovery",
                "target": "schema-verifier",
                "type": "workflow",
                "weight": 0.9,
                "description": "Recovered workbook should be verified.",
            },
            {
                "source": "pdf-extract",
                "target": "xlsx-recovery",
                "type": "dependency",
                "weight": 0.6,
                "description": "PDF evidence may support workbook recovery.",
            },
            {
                "source": "java-csv-pipeline",
                "target": "python-csv-pipeline",
                "type": "alternative",
                "weight": 0.8,
                "description": "Alternative CSV implementation paths.",
            },
        ],
    }


def test_offline_goskills_bundle_contains_typed_relations() -> None:
    bundle = build_group_graph(sample_bundle())
    graph = bundle["group_graph"]
    relation_types = {edge["type"] for edge in graph["edges"]}

    assert graph["version"] >= 1
    assert len(graph["groups"]) == len(sample_bundle()["skills"])
    assert MAX_GROUP_SIZE == 3
    assert CANDIDATE_POOL_CAP == 32
    assert all(len(group["members"]) <= 3 for group in graph["groups"])
    assert "support" in relation_types
    assert "artifact" in relation_types
    assert "verifier" in relation_types
    assert "fallback" in relation_types
    assert "conflict" in relation_types


def test_goskills_retrieval_selects_anchor_and_verifier_without_conflict() -> None:
    bundle = build_group_graph(sample_bundle())
    result = retrieve(
        bundle,
        "recover missing xlsx workbook cells and verify expected output schema",
        top_n=4,
        propagation_mode="ppr",
    )

    assert result["budget"]["selection_mode"] == "goskills_group_plan"
    assert result["budget"]["seed_top_k"] == 4
    assert result["budget"]["max_selected_groups"] == MAX_SELECTED_GROUPS == 3
    assert result["budget"]["max_backfill_skills"] == MAX_BACKFILL_SKILLS == 2
    assert result["budget"]["conflict_free"] is True
    assert result["groups"][0]["anchor"] == "xlsx-recovery"
    assert any(skill["name"] == "schema-verifier" for skill in result["coalition"])
    assert result["budget"]["ability_coverage"] > 0.0
    assert "### Debt" in result["summary"]
    assert "### Debt" in result["rendered_context"]
    assert "coverage_debt" in result
