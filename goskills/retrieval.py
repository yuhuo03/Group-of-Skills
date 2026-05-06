from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .group_graph import GROUP_RELATION_WEIGHTS, ensure_group_graph, skill_name, skill_tokens
from .text import (
    VERIFIER_HINTS,
    build_idf_weights,
    decompose_query,
    query_focus_tokens,
    signature_tokens,
    split_lines,
    unique_preserving_order,
    weighted_gain,
    weighted_overlap,
)


EXPANSION_RELATION_BONUS = {
    "support": 0.95,
    "artifact": 0.78,
    "verifier": 0.88,
    "fallback": 0.30,
}

MAX_SELECTED_GROUPS = 3
MAX_BACKFILL_SKILLS = 2
GROUP_SELECTION_MIN_SCORE = 0.14
SUPPORT_SELECTION_MIN_SCORE = 0.10


def clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def current_skills_dir() -> str | None:
    import os

    return os.getenv("GOSKILLS_SKILLS_DIR") or os.getenv("GOS_SKILLS_DIR")


def rewrite_source_path(source_path: str, skills_dir: str | None) -> str:
    if not source_path or not skills_dir:
        return source_path
    normalized = source_path.replace("\\", "/").rstrip("/")
    if normalized.endswith("/SKILL.md"):
        skill = normalized.split("/")[-2]
        return f"{skills_dir.rstrip('/')}/{skill}/SKILL.md"
    return source_path


def render_skill_payload(skill: dict[str, Any], max_chars: int, skills_dir: str | None) -> str:
    content = (
        skill.get("raw_content")
        or skill.get("rendered_snippet")
        or f"{skill.get('name', '')}\n\n{skill.get('description', '')}"
    )
    source = rewrite_source_path(str(skill.get("source_path", "")), skills_dir)
    return "\n".join(
        [
            f"## Skill: {skill.get('name', '')}",
            f"Source: {source or 'inline'}",
            clip_text(str(content), max_chars),
        ]
    )


def build_transition(skills: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[int, float]]:
    name_to_index = {skill_name(skill): index for index, skill in enumerate(skills)}
    transition: list[dict[int, float]] = [dict() for _ in skills]
    reverse_weights = {"dependency": 0.75, "workflow": 0.45, "semantic": 0.18, "alternative": 0.08}
    forward_weights = {"dependency": 1.0, "workflow": 0.85, "semantic": 0.35, "alternative": 0.16}
    for edge in edges:
        source = name_to_index.get(str(edge.get("source") or ""))
        target = name_to_index.get(str(edge.get("target") or ""))
        if source is None or target is None or source == target:
            continue
        edge_type = str(edge.get("type", "semantic"))
        raw = max(0.0, float(edge.get("weight", 1.0) or 1.0))
        forward = raw * forward_weights.get(edge_type, 0.25)
        if forward <= 0.0:
            continue
        transition[source][target] = transition[source].get(target, 0.0) + forward
        reverse = forward * reverse_weights.get(edge_type, 0.0)
        if reverse > 0.0:
            transition[target][source] = transition[target].get(source, 0.0) + reverse
    for index, row in enumerate(transition):
        if not row:
            row[index] = 1.0
            continue
        total = sum(row.values())
        if total <= 0.0:
            row.clear()
            row[index] = 1.0
            continue
        for target, value in list(row.items()):
            row[target] = value / total
    return transition


def personalized_pagerank(
    transition: list[dict[int, float]],
    personalization: list[float],
    *,
    damping: float = 0.20,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> list[float]:
    if not transition:
        return []
    scores = list(personalization)
    for _ in range(max_iter):
        next_scores = [damping * value for value in personalization]
        factor = 1.0 - damping
        for source, row in enumerate(transition):
            source_score = scores[source]
            if source_score <= 0.0:
                continue
            for target, weight in row.items():
                next_scores[target] += factor * weight * source_score
        delta = sum(abs(left - right) for left, right in zip(next_scores, scores))
        scores = next_scores
        if delta <= tol:
            break
    total = sum(scores)
    if total > 0.0:
        scores = [score / total for score in scores]
    return scores


def lexical_skill_scores(query: str, skills: list[dict[str, Any]]) -> list[tuple[int, float]]:
    token_map = {skill_name(skill): skill_tokens(skill) for skill in skills}
    query_tokens = signature_tokens([query])
    query_weights = build_idf_weights(token_map, query_tokens=query_tokens)
    scored: list[tuple[int, float]] = []
    for index, skill in enumerate(skills):
        name = skill_name(skill)
        tokens = token_map.get(name, set())
        name_tokens = signature_tokens([name])
        source_tokens = signature_tokens([skill.get("source_path", ""), "\n".join(split_lines(skill.get("script_entrypoints", [])))])
        score = (
            (0.55 * weighted_overlap(tokens, query_weights))
            + (0.30 * weighted_overlap(name_tokens, query_weights))
            + (0.15 * weighted_overlap(source_tokens, query_weights))
        )
        if score > 0.0:
            scored.append((index, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def rank_skills(
    query: str,
    skills: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    seed_top_k: int,
    propagation_mode: str,
) -> list[dict[str, Any]]:
    lexical = lexical_skill_scores(query, skills)
    if not lexical:
        return []
    seed_count = max(1, seed_top_k)
    seed_lexical = lexical[:seed_count]
    if propagation_mode == "none":
        scores_by_index = {index: score for index, score in seed_lexical}
    elif propagation_mode == "ppr":
        personalization = [0.0] * len(skills)
        total = sum(score for _index, score in seed_lexical)
        for index, score in seed_lexical:
            personalization[index] = score / total if total > 0.0 else 0.0
        scores = personalized_pagerank(build_transition(skills, edges), personalization)
        scores_by_index = {index: score for index, score in enumerate(scores)}
    else:
        raise RuntimeError(f"Unsupported propagation mode: {propagation_mode}")

    ranked: list[dict[str, Any]] = []
    lexical_rank = {index: rank + 1 for rank, (index, _score) in enumerate(lexical)}
    for index in sorted(scores_by_index, key=lambda idx: scores_by_index[idx], reverse=True):
        skill = skills[index]
        score = float(scores_by_index[index])
        if score <= 0.0:
            continue
        ranked.append(
            {
                **skill,
                "score": score,
                "semantic_rank": lexical_rank.get(index),
            }
        )
    return ranked


def group_token_set(group: dict[str, Any]) -> set[str]:
    return set(group.get("group_tokens", [])) | set(group.get("capability_tokens", [])) | set(group.get("artifact_tokens", []))


def score_groups(
    groups: list[dict[str, Any]],
    ranked_skills: list[dict[str, Any]],
    query_decomposition: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], dict[str, float], dict[str, float]]:
    token_map = {group["group_id"]: group_token_set(group) for group in groups}
    query_tokens = query_focus_tokens(query_decomposition)
    query_weights = build_idf_weights(token_map, query_tokens=query_tokens)
    skill_scores = {skill_name(skill): float(skill.get("score", 0.0) or 0.0) for skill in ranked_skills}
    max_skill_score = max(skill_scores.values(), default=1.0)
    if max_skill_score <= 0.0:
        max_skill_score = 1.0
    normalized_skill_scores = {name: score / max_skill_score for name, score in skill_scores.items()}

    scored: list[dict[str, Any]] = []
    wants_verifier = bool(set(query_decomposition.get("tokens", [])) & VERIFIER_HINTS)
    for group in groups:
        tokens = token_map[group["group_id"]]
        matched_tokens = sorted(token for token in query_weights if token in tokens)
        coverage = weighted_overlap(tokens, query_weights)
        artifact_match = weighted_overlap(set(group.get("artifact_tokens", [])), query_weights)
        verifier_match = weighted_overlap(set(group.get("verifier_tokens", [])) | set(group.get("role_tokens", [])), query_weights)
        anchor_rank = normalized_skill_scores.get(str(group.get("anchor", "")), 0.0)
        member_rank = max((normalized_skill_scores.get(member, 0.0) for member in group.get("members", [])), default=0.0)
        role_balance = min(1.0, len(set(group.get("role_tokens", []))) / 4.0)
        verifier_bonus = 0.06 if wants_verifier and ("verifier" in set(group.get("role_tokens", [])) or group.get("verifier_tokens")) else 0.0
        score = (
            (0.38 * coverage)
            + (0.23 * anchor_rank)
            + (0.13 * member_rank)
            + (0.10 * artifact_match)
            + (0.07 * verifier_match)
            + (0.05 * role_balance)
            + (0.04 * float(group.get("group_prior", 0.0) or 0.0))
            + verifier_bonus
        )
        if score < GROUP_SELECTION_MIN_SCORE:
            continue
        scored.append(
            {
                **group,
                "group_score": score,
                "matched_query_tokens": matched_tokens,
                "coverage_score": coverage,
                "artifact_match": artifact_match,
                "verifier_match": verifier_match,
                "anchor_rank_score": anchor_rank,
            }
        )
    scored.sort(
        key=lambda group: (
            float(group.get("group_score", 0.0)),
            len(group.get("matched_query_tokens", [])),
            float(group.get("anchor_rank_score", 0.0)),
        ),
        reverse=True,
    )
    return scored, query_weights, normalized_skill_scores


def build_group_edge_indexes(group_edges: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in group_edges:
        source = str(edge.get("source_group") or "")
        target = str(edge.get("target_group") or "")
        if not source or not target or source == target:
            continue
        outgoing[source].append(edge)
        pair[(source, target)].append(edge)
    for edges in outgoing.values():
        edges.sort(key=lambda item: float(item.get("weight", 0.0) or 0.0), reverse=True)
    return outgoing, pair


def best_relation(
    selected_ids: set[str],
    candidate_id: str,
    pair_edges: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    include_conflict: bool = False,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for selected_id in selected_ids:
        for edge in pair_edges.get((selected_id, candidate_id), []) + pair_edges.get((candidate_id, selected_id), []):
            relation_type = str(edge.get("type", ""))
            if relation_type == "conflict" and not include_conflict:
                continue
            if relation_type not in EXPANSION_RELATION_BONUS and relation_type != "conflict":
                continue
            if best is None or float(edge.get("weight", 0.0) or 0.0) > float(best.get("weight", 0.0) or 0.0):
                best = edge
    return best


def conflict_edge(
    selected_ids: set[str],
    candidate_id: str,
    pair_edges: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    for selected_id in selected_ids:
        for edge in pair_edges.get((selected_id, candidate_id), []) + pair_edges.get((candidate_id, selected_id), []):
            if str(edge.get("type")) == "conflict" and float(edge.get("weight", 0.0) or 0.0) >= 0.30:
                return edge
    return None


def relation_role(relation_type: str, index: int) -> str:
    if index == 0:
        return "anchor-group"
    if relation_type in {"support", "artifact", "verifier", "fallback"}:
        return f"{relation_type}-group"
    return f"support-group-{index}"


def group_expansion_candidates(
    selected_ids: set[str],
    outgoing_edges: dict[str, list[dict[str, Any]]],
) -> set[str]:
    candidates: set[str] = set()
    for group_id in selected_ids:
        for edge in outgoing_edges.get(group_id, []):
            if str(edge.get("type")) != "conflict":
                candidates.add(str(edge.get("target_group") or ""))
    candidates.discard("")
    return candidates


def select_group_coalition(
    scored_groups: list[dict[str, Any]],
    group_edges: list[dict[str, Any]],
    query_decomposition: dict[str, list[str]],
    query_weights: dict[str, float],
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not scored_groups:
        return [], [], {}

    outgoing_edges, pair_edges = build_group_edge_indexes(group_edges)
    group_by_id = {group["group_id"]: group for group in scored_groups}
    max_groups = min(MAX_SELECTED_GROUPS, max(1, top_n))
    anchor = dict(scored_groups[0])
    anchor["role"] = "anchor-group"
    anchor["selection_score"] = anchor["group_score"]
    anchor["selection_reason"] = (
        "Selected as anchor group because it has the highest query-conditioned score "
        f"and matches {', '.join(anchor.get('matched_query_tokens', [])[:5]) or 'the task core'}."
    )
    anchor["relation_from"] = None
    selected = [anchor]
    selected_ids = {anchor["group_id"]}
    covered_tokens = group_token_set(anchor) & set(query_weights)
    relation_trace: list[dict[str, Any]] = []
    wants_verifier = bool(set(query_decomposition.get("tokens", [])) & VERIFIER_HINTS)
    wants_artifact = bool(query_decomposition.get("artifacts"))

    while len(selected) < max_groups:
        frontier = group_expansion_candidates(selected_ids, outgoing_edges)
        # Let a very strong directly relevant group enter only when it adds clear coverage.
        frontier.update(group["group_id"] for group in scored_groups[: max(8, top_n * 2)])
        best: tuple[float, dict[str, Any], dict[str, Any] | None, float, float] | None = None
        for group_id in frontier:
            if group_id in selected_ids or group_id not in group_by_id:
                continue
            conflict = conflict_edge(selected_ids, group_id, pair_edges)
            if conflict is not None:
                continue
            group = group_by_id[group_id]
            relation = best_relation(selected_ids, group_id, pair_edges)
            relation_type = str(relation.get("type")) if relation else ""
            relation_weight = float(relation.get("weight", 0.0) or 0.0) if relation else 0.0
            group_tokens = group_token_set(group)
            coverage_gain = weighted_gain(group_tokens, query_weights, covered_tokens)
            if relation is None and coverage_gain < 0.16:
                continue
            if relation_type == "fallback" and coverage_gain < 0.12 and len(selected) > 1:
                continue
            role_bonus = 0.0
            if wants_verifier and relation_type == "verifier":
                role_bonus += 0.18
            if wants_artifact and relation_type == "artifact":
                role_bonus += 0.12
            relation_bonus = EXPANSION_RELATION_BONUS.get(relation_type, 0.18) * relation_weight
            selection_score = (
                (0.40 * float(group.get("group_score", 0.0) or 0.0))
                + (0.34 * coverage_gain)
                + (0.20 * relation_bonus)
                + role_bonus
            )
            if len(selected) > 0 and selection_score < SUPPORT_SELECTION_MIN_SCORE:
                continue
            if best is None or selection_score > best[0]:
                best = (selection_score, group, relation, coverage_gain, relation_bonus)
        if best is None:
            break
        selection_score, group, relation, coverage_gain, relation_bonus = best
        relation_type = str(relation.get("type")) if relation else "coverage"
        expanded = dict(group)
        expanded["role"] = relation_role(relation_type, len(selected))
        expanded["selection_score"] = selection_score
        if relation:
            reason = (
                f"Expanded via {relation_type} relation "
                f"(weight={float(relation.get('weight', 0.0) or 0.0):.3f}) "
                f"with coverage gain {coverage_gain:.3f}."
            )
            relation_trace.append(relation)
        else:
            reason = f"Expanded as a direct coverage group with coverage gain {coverage_gain:.3f}."
        expanded["selection_reason"] = reason
        expanded["relation_from"] = relation
        selected.append(expanded)
        selected_ids.add(group["group_id"])
        covered_tokens |= group_token_set(group) & set(query_weights)

    selected, relation_trace = prune_group_coalition(
        selected,
        relation_trace,
        pair_edges,
        query_decomposition,
        query_weights,
    )
    selected_ids = {group["group_id"] for group in selected}
    union_tokens: set[str] = set()
    for group in selected:
        union_tokens |= group_token_set(group)
    ability_coverage = weighted_overlap(union_tokens, query_weights)
    coherence_values = []
    for group in selected[1:]:
        relation = best_relation({selected[0]["group_id"]}, group["group_id"], pair_edges) or group.get("relation_from")
        if relation:
            relation_type = str(relation.get("type", "support"))
            coherence_values.append(float(relation.get("weight", 0.0) or 0.0) * abs(GROUP_RELATION_WEIGHTS.get(relation_type, 0.4)))
    execution_coherence = sum(coherence_values) / float(len(coherence_values) or 1)
    conflict_free = all(conflict_edge({left}, right, pair_edges) is None for left in selected_ids for right in selected_ids if left != right)
    stats = {
        "anchor_group": selected[0]["group_id"] if selected else "",
        "ability_coverage": ability_coverage,
        "execution_coherence": execution_coherence,
        "conflict_free": conflict_free,
        "selected_group_count": len(selected),
    }
    return selected, relation_trace, stats


def prune_group_coalition(
    selected: list[dict[str, Any]],
    relation_trace: list[dict[str, Any]],
    pair_edges: dict[tuple[str, str], list[dict[str, Any]]],
    query_decomposition: dict[str, list[str]],
    query_weights: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(selected) <= 1:
        return selected, relation_trace
    wants_verifier = bool(set(query_decomposition.get("tokens", [])) & VERIFIER_HINTS)
    wants_artifact = bool(query_decomposition.get("artifacts"))
    kept = [selected[0]]
    covered = group_token_set(selected[0]) & set(query_weights)
    for group in selected[1:]:
        relation = group.get("relation_from") or best_relation({kept_group["group_id"] for kept_group in kept}, group["group_id"], pair_edges)
        relation_type = str(relation.get("type")) if relation else ""
        gain = weighted_gain(group_token_set(group), query_weights, covered)
        required_by_role = (wants_verifier and relation_type == "verifier") or (wants_artifact and relation_type == "artifact")
        relation_weight = float(relation.get("weight", 0.0) or 0.0) if relation else 0.0
        if gain <= 0.025 and relation_weight < 0.42 and not required_by_role:
            continue
        if conflict_edge({kept_group["group_id"] for kept_group in kept}, group["group_id"], pair_edges) is not None:
            continue
        kept.append(group)
        covered |= group_token_set(group) & set(query_weights)

    kept_ids = {group["group_id"] for group in kept}
    kept_relations = [
        edge
        for edge in relation_trace
        if edge.get("source_group") in kept_ids and edge.get("target_group") in kept_ids
    ]
    return kept, kept_relations


def group_member_role(group: dict[str, Any], member_name: str) -> str:
    for role in group.get("roles", []):
        if role.get("skill") == member_name:
            return str(role.get("role", "support"))
    if member_name == group.get("anchor"):
        return "anchor"
    return "support"


def flatten_group_coalition(
    selected_groups: list[dict[str, Any]],
    skills_by_name: dict[str, dict[str, Any]],
    query_weights: dict[str, float],
    *,
    top_n: int,
    max_skill_chars: int,
) -> list[dict[str, Any]]:
    skills_dir = current_skills_dir()
    selected_skills: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_skill(name: str, group: dict[str, Any], reason: str, *, slot_priority: float) -> None:
        if len(selected_skills) >= top_n or name in seen or name not in skills_by_name:
            return
        base = skills_by_name[name]
        role = group_member_role(group, name)
        member_score = float(group.get("member_scores", {}).get(name, 0.65 if role == "anchor" else 0.35) or 0.0)
        coalition_score = (
            (0.58 * float(group.get("selection_score", group.get("group_score", 0.0)) or 0.0))
            + (0.22 * member_score)
            + (0.20 * slot_priority)
        )
        selected_skills.append(
            {
                **base,
                "role": role,
                "group_role": group.get("role", ""),
                "group_id": group.get("group_id", ""),
                "coalition_score": coalition_score,
                "selection_reason": reason,
                "payload": render_skill_payload(base, max_skill_chars, skills_dir),
            }
        )
        seen.add(name)

    for group in selected_groups:
        anchor = str(group.get("anchor") or "")
        add_skill(
            anchor,
            group,
            f"Anchor skill for {group.get('role')}: {group.get('selection_reason', '')}",
            slot_priority=1.0,
        )

    for group in selected_groups:
        members = [name for name in group.get("members", []) if name not in seen]
        members.sort(
            key=lambda name: (
                group_member_role(group, name) == "verifier",
                weighted_overlap(skill_tokens(skills_by_name.get(name, {})), query_weights),
                float(group.get("member_scores", {}).get(name, 0.0) or 0.0),
            ),
            reverse=True,
        )
        for member in members:
            role = group_member_role(group, member)
            member_tokens = skill_tokens(skills_by_name.get(member, {}))
            direct_match = weighted_overlap(member_tokens, query_weights)
            if role not in {"verifier", "artifact"} and direct_match <= 0.0 and len(selected_skills) >= len(selected_groups):
                continue
            add_skill(
                member,
                group,
                f"Kept from {group.get('role')} as {role} because it adds relation-local coverage.",
                slot_priority=0.85 if role in {"verifier", "artifact"} else 0.55,
            )
            if len(selected_skills) >= top_n:
                break
        if len(selected_skills) >= top_n:
            break
    return selected_skills


def selected_conflicts(
    selected_groups: list[dict[str, Any]],
    pair_edges: dict[tuple[str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    ids = [group["group_id"] for group in selected_groups]
    for left_index, left in enumerate(ids):
        for right in ids[left_index + 1 :]:
            conflict = conflict_edge({left}, right, pair_edges)
            if conflict:
                conflicts.append(conflict)
    return conflicts


def coverage_debt(
    query_decomposition: dict[str, list[str]],
    skills: list[dict[str, Any]],
    query_weights: dict[str, float],
) -> list[str]:
    required = set(query_focus_tokens(query_decomposition))
    if query_weights:
        required &= set(query_weights)
    covered: set[str] = set()
    for skill in skills:
        covered |= skill_tokens(skill)
    debt = required - covered
    return sorted(debt, key=lambda token: (query_weights.get(token, 0.0), token), reverse=True)


def backfill_debt_skills(
    selected_skills: list[dict[str, Any]],
    ranked_skills: list[dict[str, Any]],
    query_decomposition: dict[str, list[str]],
    query_weights: dict[str, float],
    *,
    top_n: int,
    max_skill_chars: int,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    debt = coverage_debt(query_decomposition, selected_skills, query_weights)
    if not debt or len(selected_skills) >= top_n:
        return selected_skills, debt, []

    skills_dir = current_skills_dir()
    seen = {skill_name(skill) for skill in selected_skills}
    backfilled: list[str] = []
    for candidate in ranked_skills:
        if len(selected_skills) >= top_n or len(backfilled) >= MAX_BACKFILL_SKILLS:
            break
        name = skill_name(candidate)
        if not name or name in seen:
            continue
        covered_debt = sorted(set(debt) & skill_tokens(candidate), key=lambda token: query_weights.get(token, 0.0), reverse=True)
        if not covered_debt:
            continue
        selected_skills.append(
            {
                **candidate,
                "role": "backfill",
                "group_role": "coverage-debt",
                "group_id": "",
                "coalition_score": float(candidate.get("score", 0.0) or 0.0),
                "selection_reason": "Backfilled because it covers remaining high-confidence facets: "
                + ", ".join(covered_debt[:6]),
                "payload": render_skill_payload(candidate, max_skill_chars, skills_dir),
            }
        )
        seen.add(name)
        backfilled.append(name)
        debt = coverage_debt(query_decomposition, selected_skills, query_weights)
        if not debt:
            break
    return selected_skills, debt, backfilled


def render_context(
    query: str,
    selected_groups: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    stats: dict[str, Any],
    query_decomposition: dict[str, list[str]],
    debt: list[str],
    *,
    max_context_chars: int,
) -> str:
    if not selected_groups:
        return "\n\n".join(
            [
                f"# GoSkills execution context for query: {query}",
                "## Retrieval Status",
                "Retrieval Status: NO_SKILL_HIT",
                "No relevant GoSkills group plan was found.",
            ]
        )
    lines = [
        f"# GoSkills execution context for query: {query}",
        "## Retrieval Status",
        "Retrieval Status: SKILL_HIT",
        "GoSkills selected an anchor-centered group plan, expanded support groups, and pruned conflicts.",
        "## Query Decomposition",
        f"- Core facets: {', '.join(query_decomposition.get('core_facets', [])) or 'task core'}",
    ]
    if query_decomposition.get("artifacts"):
        lines.append(f"- Artifacts: {', '.join(query_decomposition['artifacts'])}")
    if query_decomposition.get("operations"):
        lines.append(f"- Operations: {', '.join(query_decomposition['operations'])}")
    if query_decomposition.get("constraints"):
        lines.append(f"- Constraints: {', '.join(query_decomposition['constraints'])}")

    lines.extend(
        [
            "## Plan Diagnostics",
            f"- Anchor group: {stats.get('anchor_group', '')}",
            f"- Ability coverage: {float(stats.get('ability_coverage', 0.0)):.4f}",
            f"- Execution coherence: {float(stats.get('execution_coherence', 0.0)):.4f}",
            f"- Conflict free: {bool(stats.get('conflict_free', False))}",
            "## Group Plan",
        ]
    )
    for group in selected_groups:
        members = ", ".join(group.get("members", []))
        matched = ", ".join(group.get("matched_query_tokens", [])[:6]) or "task core"
        lines.append(
            f"- {group.get('role')}: {group.get('group_id')} ({members}) "
            f"score={float(group.get('selection_score', 0.0) or 0.0):.4f}; matched={matched}"
        )
        lines.append(f"  Why: {group.get('selection_reason', '')}")
        if group.get("artifact_tokens"):
            lines.append(f"  Artifacts: {', '.join(group.get('artifact_tokens', [])[:6])}")
        if group.get("technology_tokens"):
            lines.append(f"  Technology: {', '.join(group.get('technology_tokens', [])[:6])}")
    if relations:
        lines.append("## Group Relations")
        for relation in relations:
            lines.append(
                f"- {relation.get('source_group')} --{relation.get('type')}:{float(relation.get('weight', 0.0) or 0.0):.3f}--> "
                f"{relation.get('target_group')}: {relation.get('description', '')}"
            )
    lines.append("## Execution Contract")
    anchor_group = selected_groups[0]
    lines.append("### Start")
    lines.append(
        f"- Use `{anchor_group.get('anchor')}` first because it anchors "
        f"`{anchor_group.get('group_id')}` for the task core."
    )
    group_ids_with_presented_skills = {str(skill.get("group_id") or "") for skill in skills}
    support_groups = [
        group
        for group in selected_groups[1:]
        if group.get("group_id") in group_ids_with_presented_skills
        and "fallback" not in str(group.get("role", ""))
    ]
    lines.append("### Support")
    if support_groups:
        for group in support_groups:
            lines.append(f"- `{group.get('group_id')}` as {group.get('role')}: {group.get('selection_reason', '')}")
    else:
        lines.append("- No additional support group is required under the current budget.")
    lines.append("### Check")
    verifier_skills = [skill for skill in skills if skill.get("role") == "verifier"]
    if verifier_skills:
        for skill in verifier_skills:
            lines.append(f"- Use `{skill.get('name')}` for the smallest visible check before finalizing.")
    else:
        lines.append("- Inspect visible tests, schemas, and required output paths before finalizing.")
    lines.append("### Avoid")
    lines.extend(
        [
            "- Treat fallback groups as alternatives if the anchor path fails, not as extra work.",
            "- Do not combine groups connected by a conflict relation.",
            "- Do not expose unselected library skills unless they close an explicit visible requirement.",
        ]
    )
    lines.append("### Debt")
    if debt:
        lines.append("- Remaining high-confidence visible requirements: " + ", ".join(debt[:12]))
    else:
        lines.append("- No remaining high-confidence visible requirement is uncovered by the presented skills.")
    lines.append("### Skills")
    for skill in skills:
        lines.append(
            f"- {skill.get('role')} [{skill.get('group_role')}]: {skill.get('name')} "
            f"(coalition score={float(skill.get('coalition_score', 0.0) or 0.0):.4f})"
        )
        lines.append(f"  Why: {skill.get('selection_reason', '')}")
        if skill.get("source_path"):
            lines.append(f"  Source: {skill.get('source_path')}")
    for skill in skills:
        lines.append(skill.get("payload", ""))
    return clip_text("\n".join(lines), max_context_chars)


def render_summary(
    query: str,
    selected_groups: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    stats: dict[str, Any],
    query_decomposition: dict[str, list[str]],
    debt: list[str],
) -> str:
    if not selected_groups:
        return "\n".join(
            [
                "### Retrieval Status",
                "- Retrieval Status: NO_SKILL_HIT",
                "- No relevant GoSkills group plan was found for this query.",
                f"- Query: {query}",
            ]
        )
    lines = [
        "### Retrieval Status",
        "- Retrieval Status: SKILL_HIT",
        "- GoSkills selected an anchor-centered group plan and expanded over typed group relations with conflict pruning.",
        "",
        "### Anchor Group",
        f"- `{selected_groups[0]['group_id']}` anchored by `{selected_groups[0].get('anchor')}`",
        f"- Ability coverage: {float(stats.get('ability_coverage', 0.0)):.4f}",
        f"- Execution coherence: {float(stats.get('execution_coherence', 0.0)):.4f}",
        f"- Conflict free: {bool(stats.get('conflict_free', False))}",
        "",
        "### Query Decomposition",
        f"- Core facets: {', '.join(query_decomposition.get('core_facets', [])) or 'task core'}",
    ]
    if query_decomposition.get("artifacts"):
        lines.append(f"- Artifacts: {', '.join(query_decomposition['artifacts'])}")
    if query_decomposition.get("operations"):
        lines.append(f"- Operations: {', '.join(query_decomposition['operations'])}")
    if query_decomposition.get("constraints"):
        lines.append(f"- Constraints: {', '.join(query_decomposition['constraints'])}")
    lines.extend(["", "### Group Plan"])
    for group in selected_groups:
        matched = ", ".join(group.get("matched_query_tokens", [])[:6]) or "task core"
        lines.append(
            f"- {group.get('role')}: `{group.get('group_id')}` "
            f"score={float(group.get('selection_score', 0.0) or 0.0):.4f}; matched={matched}"
        )
        lines.append(f"  Why: {group.get('selection_reason', '')}")
    if relations:
        lines.extend(["", "### Expansion Relations"])
        for relation in relations:
            lines.append(
                f"- {relation.get('source_group')} --{relation.get('type')}:{float(relation.get('weight', 0.0) or 0.0):.3f}--> "
                f"{relation.get('target_group')}"
            )
    lines.extend(["", "### Presented Skills"])
    for skill in skills:
        source = f"; Source: {skill.get('source_path')}" if skill.get("source_path") else ""
        lines.append(
            f"- {skill.get('role')} [{skill.get('group_role')}]: `{skill.get('name')}` "
            f"score={float(skill.get('coalition_score', 0.0) or 0.0):.4f}{source}"
        )
    lines.extend(["", "### Debt"])
    if debt:
        lines.append("- Remaining high-confidence visible requirements: " + ", ".join(debt[:12]))
    else:
        lines.append("- No remaining high-confidence visible requirement is uncovered by the presented skills.")
    return "\n".join(lines)


def fit_skills_to_budget(query: str, skills: list[dict[str, Any]], max_context_chars: int) -> list[dict[str, Any]]:
    if max_context_chars <= 0:
        return []
    total = len(query) + 512
    kept: list[dict[str, Any]] = []
    for skill in skills:
        payload = str(skill.get("payload", ""))
        remaining = max_context_chars - total
        if remaining <= 0:
            break
        updated = dict(skill)
        if len(payload) > remaining:
            updated["payload"] = clip_text(payload, remaining)
        kept.append(updated)
        total += len(updated.get("payload", "")) + 128
    return kept


def retrieve(
    bundle: dict[str, Any],
    query: str,
    *,
    top_n: int = 4,
    seed_top_k: int = 4,
    max_skill_chars: int = 1800,
    max_context_chars: int = 9000,
    seed_mode: str = "lexical",
    propagation_mode: str = "ppr",
    vector_store_path: Path | None = None,
) -> dict[str, Any]:
    del vector_store_path
    if seed_mode != "lexical":
        raise RuntimeError("GoSkills currently supports lexical seed mode only")
    empty_budget = {
        "top_n": top_n,
        "seed_top_k": seed_top_k,
        "max_skill_chars": max_skill_chars,
        "max_context_chars": max_context_chars,
        "max_selected_groups": MAX_SELECTED_GROUPS,
        "max_backfill_skills": MAX_BACKFILL_SKILLS,
        "seed_mode": seed_mode,
        "propagation_mode": propagation_mode,
        "selection_mode": "goskills_group_plan",
        "anchor_group": "",
        "ability_coverage": 0.0,
        "execution_coherence": 0.0,
        "conflict_free": True,
        "coverage_debt": [],
        "backfilled_skills": [],
    }
    if not query.strip():
        return {
            "query": query,
            "summary": "Empty query.",
            "rendered_context": "",
            "query_decomposition": {},
            "skills": [],
            "coalition": [],
            "groups": [],
            "relations": [],
            "budget": empty_budget,
        }

    bundle = ensure_group_graph(bundle)
    graph = bundle.get("group_graph", {})
    groups = list(graph.get("groups", bundle.get("groups", [])))
    group_edges = list(graph.get("edges", bundle.get("group_edges", [])))
    skills = [skill for skill in bundle.get("skills", []) if skill_name(skill)]
    edges = list(bundle.get("edges", []))
    vocabulary = {token for group in groups for token in group_token_set(group)}
    query_decomposition = decompose_query(query, vocabulary=vocabulary)
    ranked = rank_skills(query, skills, edges, seed_top_k=seed_top_k, propagation_mode=propagation_mode)
    if not ranked:
        debt = coverage_debt(query_decomposition, [], {})
        budget = {**empty_budget, "coverage_debt": debt}
        summary = render_summary(query, [], [], [], {}, query_decomposition, debt)
        context = render_context(query, [], [], [], {}, query_decomposition, debt, max_context_chars=max_context_chars)
        return {
            "query": query,
            "summary": summary,
            "rendered_context": context,
            "query_decomposition": query_decomposition,
            "skills": [],
            "coalition": [],
            "groups": [],
            "relations": [],
            "budget": budget,
        }

    scored_groups, query_weights, _normalized_skill_scores = score_groups(groups, ranked, query_decomposition)
    if not scored_groups or float(scored_groups[0].get("group_score", 0.0) or 0.0) < 0.015:
        debt = coverage_debt(query_decomposition, [], query_weights)
        budget = {**empty_budget, "coverage_debt": debt}
        summary = render_summary(query, [], [], [], {}, query_decomposition, debt)
        context = render_context(query, [], [], [], {}, query_decomposition, debt, max_context_chars=max_context_chars)
        return {
            "query": query,
            "summary": summary,
            "rendered_context": context,
            "query_decomposition": query_decomposition,
            "skills": [],
            "coalition": [],
            "groups": [],
            "relations": [],
            "budget": budget,
        }

    selected_groups, relations, stats = select_group_coalition(
        scored_groups,
        group_edges,
        query_decomposition,
        query_weights,
        top_n=top_n,
    )
    ranked_by_name = {skill_name(skill): skill for skill in ranked}
    coalition_skills = flatten_group_coalition(
        selected_groups,
        ranked_by_name,
        query_weights,
        top_n=top_n,
        max_skill_chars=max_skill_chars,
    )
    coalition_skills, debt, backfilled_skills = backfill_debt_skills(
        coalition_skills,
        ranked,
        query_decomposition,
        query_weights,
        top_n=top_n,
        max_skill_chars=max_skill_chars,
    )
    coalition_skills = fit_skills_to_budget(query, coalition_skills, max_context_chars)
    kept_skill_names = {skill_name(skill) for skill in coalition_skills}
    backfilled_skills = [name for name in backfilled_skills if name in kept_skill_names]
    debt = coverage_debt(query_decomposition, coalition_skills, query_weights)
    kept_group_ids = {skill.get("group_id") for skill in coalition_skills}
    selected_groups = [group for group in selected_groups if group.get("group_id") in kept_group_ids]
    stats.update(
        {
            "selected_group_count": len(selected_groups),
            "selected_skill_count": len(coalition_skills),
            "coverage_debt": debt,
            "backfilled_skills": backfilled_skills,
        }
    )
    summary = render_summary(query, selected_groups, coalition_skills, relations, stats, query_decomposition, debt)
    context = render_context(
        query,
        selected_groups,
        coalition_skills,
        relations,
        stats,
        query_decomposition,
        debt,
        max_context_chars=max_context_chars,
    )
    budget = {
        **empty_budget,
        "anchor_group": stats.get("anchor_group", ""),
        "ability_coverage": stats.get("ability_coverage", 0.0),
        "execution_coherence": stats.get("execution_coherence", 0.0),
        "conflict_free": stats.get("conflict_free", True),
        "group_count": len(groups),
        "group_edge_count": len(group_edges),
        "selected_group_count": len(selected_groups),
        "selected_skill_count": len(coalition_skills),
        "coverage_debt": debt,
        "backfilled_skills": backfilled_skills,
    }
    return {
        "query": query,
        "summary": summary,
        "rendered_context": context,
        "query_decomposition": query_decomposition,
        "skills": coalition_skills,
        "coalition": [
            {
                "role": skill.get("role", ""),
                "group_role": skill.get("group_role", ""),
                "name": skill.get("name", ""),
                "score": skill.get("coalition_score", 0.0),
                "selection_reason": skill.get("selection_reason", ""),
                "source_path": skill.get("source_path", ""),
            }
            for skill in coalition_skills
        ],
        "groups": [
            {
                "group_id": group.get("group_id", ""),
                "role": group.get("role", ""),
                "anchor": group.get("anchor", ""),
                "score": group.get("group_score", 0.0),
                "selection_score": group.get("selection_score", 0.0),
                "selection_reason": group.get("selection_reason", ""),
                "matched_query_tokens": group.get("matched_query_tokens", []),
                "members": group.get("members", []),
                "artifact_tokens": group.get("artifact_tokens", []),
                "technology_tokens": group.get("technology_tokens", []),
                "roles_template": group.get("roles", []),
            }
            for group in selected_groups
        ],
        "relations": relations,
        "budget": budget,
        "coverage_debt": debt,
        "backfilled_skills": backfilled_skills,
    }


def retrieve_from_path(bundle_path: Path, query: str, **kwargs: Any) -> dict[str, Any]:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    return retrieve(bundle, query, **kwargs)
