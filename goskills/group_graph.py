from __future__ import annotations

from collections import defaultdict
from typing import Any

from .text import (
    FILE_FORMAT_TOKENS,
    TECH_TOKENS,
    VERIFIER_HINTS,
    build_idf_weights,
    signature_tokens,
    slugify,
    split_lines,
    technology_family_conflict,
    token_jaccard,
    unique_preserving_order,
    weighted_overlap,
)


GROUP_GRAPH_VERSION = 1

SKILL_EDGE_WEIGHTS = {
    "dependency": 1.0,
    "workflow": 0.85,
    "semantic": 0.35,
    "alternative": 0.25,
}

GROUP_RELATION_WEIGHTS = {
    "support": 1.0,
    "artifact": 0.82,
    "verifier": 0.90,
    "fallback": 0.38,
    "conflict": -1.0,
}

MAX_GROUP_SIZE = 3
CANDIDATE_POOL_CAP = 32
SUPPORT_SKILL_MIN_SCORE = 0.10
SEMANTIC_SUPPORT_MIN_SCORE = 0.14


def skill_name(skill: dict[str, Any]) -> str:
    return str(skill.get("name") or "").strip()


def skill_tokens(skill: dict[str, Any]) -> set[str]:
    values: list[str] = [
        skill.get("name", ""),
        skill.get("description", ""),
        skill.get("source_path", ""),
        skill.get("rendered_snippet", ""),
    ]
    values.extend(split_lines(skill.get("inputs", [])))
    values.extend(split_lines(skill.get("outputs", [])))
    values.extend(split_lines(skill.get("allowed_tools", [])))
    values.extend(split_lines(skill.get("script_entrypoints", [])))
    return signature_tokens(values)


def skill_artifacts(skill: dict[str, Any]) -> set[str]:
    values: list[str] = []
    values.extend(split_lines(skill.get("inputs", [])))
    values.extend(split_lines(skill.get("outputs", [])))
    values.extend(split_lines(skill.get("source_path", "")))
    values.extend(split_lines(skill.get("script_entrypoints", [])))
    tokens = signature_tokens(values)
    explicit_formats = tokens & FILE_FORMAT_TOKENS
    structured = {token for token in tokens if "_" in token and 3 <= len(token) <= 48}
    return set(sorted(explicit_formats | structured))


def skill_tech_tokens(skill: dict[str, Any]) -> set[str]:
    return skill_tokens(skill) & TECH_TOKENS


def skill_has_verifier_signature(skill: dict[str, Any]) -> bool:
    tokens = skill_tokens(skill)
    return bool(tokens & VERIFIER_HINTS)


def build_edge_indexes(
    edges: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[frozenset[str], list[dict[str, Any]]]]:
    directed: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    undirected: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target or source == target:
            continue
        directed[source][target].append(edge)
        undirected[frozenset((source, target))].append(edge)
    return directed, undirected


def strongest_skill_edge(
    left: str,
    right: str,
    undirected_edges: dict[frozenset[str], list[dict[str, Any]]],
) -> tuple[float, str, str]:
    best_weight = 0.0
    best_type = "semantic"
    best_description = ""
    for edge in undirected_edges.get(frozenset((left, right)), []):
        edge_type = str(edge.get("type", "semantic"))
        raw_weight = float(edge.get("weight", 1.0) or 1.0)
        adjusted = raw_weight * SKILL_EDGE_WEIGHTS.get(edge_type, 0.25)
        if adjusted > best_weight:
            best_weight = adjusted
            best_type = edge_type
            best_description = str(edge.get("description", ""))
    return best_weight, best_type, best_description


def member_role(
    anchor: dict[str, Any],
    member: dict[str, Any],
    relation_type: str,
    *,
    artifact_map: dict[str, set[str]] | None = None,
    verifier_map: dict[str, bool] | None = None,
) -> str:
    anchor_name = skill_name(anchor)
    member_name = skill_name(member)
    if anchor_name == member_name:
        return "anchor"
    if relation_type == "alternative":
        return "fallback"
    member_is_verifier = (
        verifier_map.get(member_name, False)
        if verifier_map is not None
        else skill_has_verifier_signature(member)
    )
    if member_is_verifier:
        return "verifier"
    if artifact_map is not None:
        anchor_artifacts = artifact_map.get(anchor_name, set())
        member_artifacts = artifact_map.get(member_name, set())
    else:
        anchor_artifacts = skill_artifacts(anchor)
        member_artifacts = skill_artifacts(member)
    if anchor_artifacts & member_artifacts:
        return "artifact"
    return "support"


def score_anchor_member(
    anchor: dict[str, Any],
    candidate: dict[str, Any],
    *,
    token_map: dict[str, set[str]],
    artifact_map: dict[str, set[str]],
    verifier_map: dict[str, bool] | None = None,
    corpus_weights: dict[str, float],
    undirected_edges: dict[frozenset[str], list[dict[str, Any]]],
) -> tuple[float, str, str]:
    anchor_name = skill_name(anchor)
    candidate_name = skill_name(candidate)
    explicit, relation_type, description = strongest_skill_edge(anchor_name, candidate_name, undirected_edges)
    lexical = token_jaccard(token_map.get(anchor_name, set()), token_map.get(candidate_name, set()))
    shared_artifact = token_jaccard(artifact_map.get(anchor_name, set()), artifact_map.get(candidate_name, set()))
    shared_signal = weighted_overlap(
        token_map.get(anchor_name, set()) & token_map.get(candidate_name, set()),
        corpus_weights,
    )
    candidate_is_verifier = (
        verifier_map.get(candidate_name, False)
        if verifier_map is not None
        else skill_has_verifier_signature(candidate)
    )
    verifier_bonus = 0.12 if candidate_is_verifier else 0.0
    score = (
        (0.50 * explicit)
        + (0.22 * lexical)
        + (0.16 * min(1.0, shared_signal))
        + (0.12 * shared_artifact)
        + verifier_bonus
    )
    return score, relation_type, description


def group_tokens_for_members(
    members: list[str],
    *,
    token_map: dict[str, set[str]],
    artifact_map: dict[str, set[str]],
) -> tuple[set[str], set[str]]:
    tokens: set[str] = set()
    artifacts: set[str] = set()
    for member in members:
        tokens |= token_map.get(member, set())
        artifacts |= artifact_map.get(member, set())
    return tokens, artifacts


def build_anchor_group(
    anchor: dict[str, Any],
    *,
    skills: list[dict[str, Any]],
    candidate_skill_names: set[str] | None = None,
    skill_lookup: dict[str, dict[str, Any]] | None = None,
    token_map: dict[str, set[str]],
    artifact_map: dict[str, set[str]],
    verifier_map: dict[str, bool] | None = None,
    corpus_weights: dict[str, float],
    undirected_edges: dict[frozenset[str], list[dict[str, Any]]],
    max_group_size: int,
) -> dict[str, Any]:
    anchor_name = skill_name(anchor)
    candidates: list[tuple[float, str, str, dict[str, Any], str]] = []
    if candidate_skill_names is not None and skill_lookup is not None:
        candidate_iterable = (
            skill_lookup[candidate_name]
            for candidate_name in candidate_skill_names
            if candidate_name in skill_lookup and candidate_name != anchor_name
        )
    else:
        candidate_iterable = iter(skills)
    for candidate in candidate_iterable:
        candidate_name = skill_name(candidate)
        if candidate_name == anchor_name:
            continue
        if candidate_skill_names is not None and candidate_name not in candidate_skill_names:
            continue
        score, relation_type, description = score_anchor_member(
            anchor,
            candidate,
            token_map=token_map,
            artifact_map=artifact_map,
            verifier_map=verifier_map,
            corpus_weights=corpus_weights,
            undirected_edges=undirected_edges,
        )
        if score < SUPPORT_SKILL_MIN_SCORE:
            continue
        if relation_type == "semantic" and score < SEMANTIC_SUPPORT_MIN_SCORE:
            continue
        candidates.append((score, relation_type, description, candidate, candidate_name))
    candidates.sort(key=lambda item: item[0], reverse=True)

    members = [anchor_name]
    roles = [{"skill": anchor_name, "role": "anchor", "required": True, "score": 1.0}]
    role_seen = {"anchor"}
    member_scores = {anchor_name: 1.0}

    # Keep compact groups but reserve room for at least one verifier when possible.
    verifier_candidate: tuple[float, str, str, dict[str, Any], str] | None = None
    for item in candidates:
        item_is_verifier = (
            verifier_map.get(item[4], False)
            if verifier_map is not None
            else skill_has_verifier_signature(item[3])
        )
        if item_is_verifier:
            verifier_candidate = item
            break

    for score, relation_type, description, candidate, candidate_name in candidates:
        if len(members) >= max_group_size:
            break
        role = member_role(
            anchor,
            candidate,
            relation_type,
            artifact_map=artifact_map,
            verifier_map=verifier_map,
        )
        if role == "verifier" and "verifier" in role_seen:
            continue
        if role == "fallback" and "fallback" in role_seen:
            continue
        members.append(candidate_name)
        roles.append(
            {
                "skill": candidate_name,
                "role": role,
                "required": role in {"support", "artifact"} and relation_type in {"dependency", "workflow"},
                "score": round(score, 6),
                "evidence": description or relation_type,
            }
        )
        role_seen.add(role)
        member_scores[candidate_name] = round(score, 6)

    if (
        verifier_candidate is not None
        and "verifier" not in role_seen
        and verifier_candidate[4] not in members
        and len(members) < max_group_size
    ):
        score, relation_type, description, _candidate, candidate_name = verifier_candidate
        members.append(candidate_name)
        roles.append(
            {
                "skill": candidate_name,
                "role": "verifier",
                "required": False,
                "score": round(score, 6),
                "evidence": description or relation_type,
            }
        )
        member_scores[candidate_name] = round(score, 6)

    group_token_set, group_artifacts = group_tokens_for_members(
        members,
        token_map=token_map,
        artifact_map=artifact_map,
    )
    role_tokens = {str(role["role"]) for role in roles}
    verifier_tokens = group_token_set & VERIFIER_HINTS
    tech_tokens = group_token_set & TECH_TOKENS
    capability_tokens = sorted(
        token
        for token in group_token_set
        if token not in FILE_FORMAT_TOKENS and token not in TECH_TOKENS and len(token) >= 3
    )[:16]
    group_prior = min(
        1.0,
        0.42
        + (0.10 * (len(members) - 1))
        + (0.08 if verifier_tokens else 0.0)
        + (0.08 if group_artifacts else 0.0)
        + (0.04 * min(len(role_tokens), 4)),
    )
    group_id = f"g-{slugify(anchor_name)}"
    return {
        "group_id": group_id,
        "anchor": anchor_name,
        "name": f"{anchor_name} group",
        "description": f"Anchor-centered group for {anchor_name}.",
        "members": members,
        "roles": roles,
        "capability_tokens": capability_tokens,
        "artifact_tokens": sorted(group_artifacts)[:12],
        "verifier_tokens": sorted(verifier_tokens),
        "technology_tokens": sorted(tech_tokens),
        "role_tokens": sorted(role_tokens),
        "group_tokens": sorted(group_token_set),
        "member_scores": member_scores,
        "group_prior": round(group_prior, 6),
    }


def build_anchor_candidate_map(
    skills: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    token_map: dict[str, set[str]],
    artifact_map: dict[str, set[str]],
    corpus_weights: dict[str, float],
    max_candidates: int = CANDIDATE_POOL_CAP,
) -> dict[str, set[str]]:
    """Retrieve likely group members without scoring every skill pair."""

    skill_by_name = {skill_name(skill): skill for skill in skills if skill_name(skill)}
    candidate_map: dict[str, set[str]] = {name: set() for name in skill_by_name}
    edge_scores: dict[str, dict[str, float]] = defaultdict(dict)

    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in candidate_map or target not in candidate_map or source == target:
            continue
        edge_type = str(edge.get("type", "semantic"))
        raw = float(edge.get("weight", 1.0) or 1.0)
        adjusted = raw * SKILL_EDGE_WEIGHTS.get(edge_type, 0.25)
        current = edge_scores[source].get(target, 0.0)
        if adjusted > current:
            edge_scores[source][target] = adjusted
        reverse_score = adjusted if edge_type in {"semantic", "alternative", "conflict"} else adjusted * 0.25
        current = edge_scores[target].get(source, 0.0)
        if reverse_score > current:
            edge_scores[target][source] = reverse_score

    token_index: dict[str, list[str]] = defaultdict(list)
    for name, tokens in token_map.items():
        for token in tokens:
            token_index[token].append(name)

    verifier_names = {name for name, tokens in token_map.items() if tokens & VERIFIER_HINTS}

    for anchor_name in skill_by_name:
        anchor_tokens = token_map.get(anchor_name, set())
        priority_tokens = set(artifact_map.get(anchor_name, set()))
        priority_tokens |= anchor_tokens & TECH_TOKENS
        priority_tokens |= anchor_tokens & VERIFIER_HINTS
        priority_tokens |= {
            token
            for token in anchor_tokens
            if "_" in token or token in corpus_weights
        }
        ranked_tokens = sorted(
            priority_tokens,
            key=lambda token: (
                token in artifact_map.get(anchor_name, set()),
                token in TECH_TOKENS,
                corpus_weights.get(token, 0.0),
                len(token),
            ),
            reverse=True,
        )[:24]

        lightweight_scores: dict[str, float] = defaultdict(float)
        for token in ranked_tokens:
            bucket = token_index.get(token, [])
            if len(bucket) < 2 or len(bucket) > 140:
                continue
            token_weight = corpus_weights.get(token, 0.0)
            if token in artifact_map.get(anchor_name, set()):
                token_weight += 0.018
            if token in TECH_TOKENS or token in VERIFIER_HINTS:
                token_weight += 0.010
            for candidate_name in bucket:
                if candidate_name != anchor_name:
                    lightweight_scores[candidate_name] += token_weight

        for candidate_name, edge_score in edge_scores.get(anchor_name, {}).items():
            if candidate_name != anchor_name:
                lightweight_scores[candidate_name] += 0.035 + edge_score

        ranked_candidates = sorted(
            lightweight_scores.items(),
            key=lambda item: (
                item[1],
                item[0] in verifier_names,
                len(token_map.get(item[0], set()) & anchor_tokens),
            ),
            reverse=True,
        )
        for candidate_name, _score in ranked_candidates[:max_candidates]:
            candidate_map[anchor_name].add(candidate_name)

        # A verifier is useful even when it is not the highest lexical match.
        verifier_count = 0
        for candidate_name, _score in ranked_candidates:
            if candidate_name in verifier_names:
                candidate_map[anchor_name].add(candidate_name)
                verifier_count += 1
            if verifier_count >= 8:
                break

    return candidate_map


def relation_key(source_group: str, target_group: str, relation_type: str) -> tuple[str, str, str]:
    return source_group, target_group, relation_type


def add_group_edge(
    edges: dict[tuple[str, str, str], dict[str, Any]],
    *,
    source_group: str,
    target_group: str,
    relation_type: str,
    weight: float,
    description: str,
    evidence: list[str] | None = None,
) -> None:
    if source_group == target_group:
        return
    key = relation_key(source_group, target_group, relation_type)
    existing = edges.get(key)
    edge = {
        "source_group": source_group,
        "target_group": target_group,
        "type": relation_type,
        "weight": round(max(0.0, min(1.0, weight)), 6),
        "description": description,
        "evidence": evidence or [],
    }
    if existing is None or edge["weight"] > existing["weight"]:
        edges[key] = edge


def group_relation_signal(
    source: dict[str, Any],
    target: dict[str, Any],
    *,
    directed_edges: dict[str, dict[str, list[dict[str, Any]]]],
    undirected_edges: dict[frozenset[str], list[dict[str, Any]]],
) -> tuple[float, float, float, float, list[str]]:
    support = 0.0
    fallback = 0.0
    explicit_conflict = 0.0
    evidence: list[str] = []
    for source_member in source.get("members", []):
        for target_member in target.get("members", []):
            for edge in directed_edges.get(source_member, {}).get(target_member, []):
                edge_type = str(edge.get("type", "semantic"))
                raw = float(edge.get("weight", 1.0) or 1.0)
                if edge_type in {"dependency", "workflow"}:
                    support = max(support, raw * SKILL_EDGE_WEIGHTS.get(edge_type, 0.8))
                    evidence.append(f"{source_member}->{target_member}:{edge_type}")
                elif edge_type == "alternative":
                    fallback = max(fallback, raw * SKILL_EDGE_WEIGHTS["alternative"])
                    evidence.append(f"{source_member}->{target_member}:alternative")
                elif edge_type == "conflict":
                    explicit_conflict = max(explicit_conflict, raw)
                    evidence.append(f"{source_member}->{target_member}:conflict")
            _strongest, edge_type, _description = strongest_skill_edge(source_member, target_member, undirected_edges)
            if edge_type == "alternative":
                fallback = max(fallback, 0.22)

    source_tokens = set(source.get("group_tokens", []))
    target_tokens = set(target.get("group_tokens", []))
    source_capabilities = set(source.get("capability_tokens", []))
    target_capabilities = set(target.get("capability_tokens", []))
    source_artifacts = set(source.get("artifact_tokens", []))
    target_artifacts = set(target.get("artifact_tokens", []))
    artifact = token_jaccard(source_artifacts, target_artifacts)
    overlap = token_jaccard(source_tokens, target_tokens)
    capability_overlap = token_jaccard(source_capabilities, target_capabilities)
    conflict = explicit_conflict
    if (
        technology_family_conflict(source_tokens, target_tokens)
        and (overlap >= 0.20 or capability_overlap >= 0.16 or artifact >= 0.18)
    ):
        conflict = max(conflict, min(1.0, 0.40 + max(overlap, capability_overlap, artifact)))
        evidence.append("technology-family-conflict")
    if source_artifacts and target_artifacts and source_artifacts.isdisjoint(target_artifacts) and overlap >= 0.36:
        conflict = max(conflict, 0.35 + min(0.35, overlap))
        evidence.append("artifact-assumption-conflict")
    return support, artifact, fallback, conflict, unique_preserving_order(evidence)[:6]


def build_group_edges(groups: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    directed_edges, undirected_edges = build_edge_indexes(edges)
    by_id = {group["group_id"]: group for group in groups}
    edge_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    anchor_to_group = {str(group.get("anchor", "")): group["group_id"] for group in groups}
    candidate_scores: dict[str, dict[str, float]] = defaultdict(dict)

    def add_candidate_pair(left_id: str, right_id: str, score: float) -> None:
        if left_id and right_id and left_id != right_id and left_id in by_id and right_id in by_id:
            current = candidate_scores[left_id].get(right_id, 0.0)
            if score > current:
                candidate_scores[left_id][right_id] = score

    # Atomic graph edges are the strongest signal for support/fallback/verifier
    # relations. Use anchor-to-anchor candidates first, then cap per source.
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        source_group = anchor_to_group.get(source)
        target_group = anchor_to_group.get(target)
        if not source_group or not target_group or source_group == target_group:
            continue
        edge_type = str(edge.get("type", "semantic"))
        raw = float(edge.get("weight", 1.0) or 1.0)
        adjusted = raw * SKILL_EDGE_WEIGHTS.get(edge_type, 0.25)
        if edge_type in {"dependency", "workflow"}:
            add_candidate_pair(source_group, target_group, adjusted)
            add_candidate_pair(target_group, source_group, adjusted * 0.25)
        else:
            add_candidate_pair(source_group, target_group, adjusted)
            add_candidate_pair(target_group, source_group, adjusted)

    def add_index_pairs(token_to_group_ids: dict[str, list[str]], *, cap_per_token: int, score: float) -> None:
        for group_ids in token_to_group_ids.values():
            unique_ids = unique_preserving_order(group_ids)
            if len(unique_ids) < 2 or len(unique_ids) > cap_per_token:
                continue
            for left_index, left_id in enumerate(unique_ids):
                for right_id in unique_ids[left_index + 1 :]:
                    add_candidate_pair(left_id, right_id, score)
                    add_candidate_pair(right_id, left_id, score)

    artifact_index: dict[str, list[str]] = defaultdict(list)
    capability_index: dict[str, list[str]] = defaultdict(list)
    verifier_index: dict[str, list[str]] = defaultdict(list)
    for group in groups:
        group_id = group["group_id"]
        for token in group.get("artifact_tokens", []):
            artifact_index[str(token)].append(group_id)
        for token in group.get("capability_tokens", []):
            capability_index[str(token)].append(group_id)
        if "verifier" in set(group.get("role_tokens", [])) or group.get("verifier_tokens"):
            for token in group.get("artifact_tokens", []) + group.get("capability_tokens", [])[:8]:
                verifier_index[str(token)].append(group_id)

    add_index_pairs(artifact_index, cap_per_token=80, score=0.32)
    add_index_pairs(capability_index, cap_per_token=36, score=0.22)
    add_index_pairs(verifier_index, cap_per_token=80, score=0.36)

    candidate_pairs: set[tuple[str, str]] = set()
    for source_id, target_scores in candidate_scores.items():
        ranked_targets = sorted(
            target_scores.items(),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )
        for target_id, _score in ranked_targets[:96]:
            candidate_pairs.add((source_id, target_id))

    for source_id, target_id in sorted(candidate_pairs):
        source = by_id[source_id]
        target = by_id[target_id]
        support, artifact, fallback, conflict, evidence = group_relation_signal(
            source,
            target,
            directed_edges=directed_edges,
            undirected_edges=undirected_edges,
        )
        if support >= 0.18:
            add_group_edge(
                edge_map,
                source_group=source_id,
                target_group=target_id,
                relation_type="support",
                weight=support,
                description=f"{target['name']} supports the workflow of {source['name']}.",
                evidence=evidence,
            )
        if artifact >= 0.18:
            add_group_edge(
                edge_map,
                source_group=source_id,
                target_group=target_id,
                relation_type="artifact",
                weight=min(1.0, 0.35 + artifact),
                description=f"{source['name']} and {target['name']} share artifact assumptions.",
                evidence=sorted(set(source.get("artifact_tokens", [])) & set(target.get("artifact_tokens", [])))[:6],
            )
        target_is_verifier = "verifier" in set(target.get("role_tokens", [])) or bool(target.get("verifier_tokens"))
        if target_is_verifier and (artifact >= 0.10 or token_jaccard(set(source.get("capability_tokens", [])), set(target.get("capability_tokens", []))) >= 0.12):
            add_group_edge(
                edge_map,
                source_group=source_id,
                target_group=target_id,
                relation_type="verifier",
                weight=min(1.0, 0.45 + artifact + (0.2 if target.get("verifier_tokens") else 0.0)),
                description=f"{target['name']} can verify outputs or constraints for {source['name']}.",
                evidence=sorted(set(target.get("verifier_tokens", [])))[:6],
            )
        if fallback >= 0.16:
            add_group_edge(
                edge_map,
                source_group=source_id,
                target_group=target_id,
                relation_type="fallback",
                weight=fallback,
                description=f"{target['name']} is an alternative route for {source['name']}.",
                evidence=evidence,
            )
        if conflict >= 0.30:
            add_group_edge(
                edge_map,
                source_group=source_id,
                target_group=target_id,
                relation_type="conflict",
                weight=conflict,
                description=f"{source['name']} conflicts with {target['name']} under shared but incompatible assumptions.",
                evidence=evidence,
            )

    # Keep the graph compact enough for online expansion.
    outgoing_by_type: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edge_map.values():
        outgoing_by_type[(edge["source_group"], edge["type"])].append(edge)

    pruned: list[dict[str, Any]] = []
    for (source_id, relation_type), relation_edges in outgoing_by_type.items():
        cap = 8 if relation_type == "conflict" else 5
        relation_edges.sort(key=lambda edge: edge["weight"], reverse=True)
        pruned.extend(relation_edges[:cap])

    pruned.sort(
        key=lambda edge: (
            edge["source_group"],
            edge["type"],
            -float(edge.get("weight", 0.0)),
            edge["target_group"],
        )
    )
    # Ensure edge endpoints still point to existing groups after any future filtering.
    return [edge for edge in pruned if edge["source_group"] in by_id and edge["target_group"] in by_id]


def build_group_graph(bundle: dict[str, Any], *, max_group_size: int = MAX_GROUP_SIZE) -> dict[str, Any]:
    skills = [skill for skill in bundle.get("skills", []) if skill_name(skill)]
    edges = list(bundle.get("edges", []))
    skill_lookup = {skill_name(skill): skill for skill in skills}
    token_map = {skill_name(skill): skill_tokens(skill) for skill in skills}
    artifact_map = {skill_name(skill): skill_artifacts(skill) for skill in skills}
    verifier_map = {name: bool(tokens & VERIFIER_HINTS) for name, tokens in token_map.items()}
    corpus_weights = build_idf_weights(token_map)
    _directed_edges, undirected_edges = build_edge_indexes(edges)
    candidate_map = build_anchor_candidate_map(
        skills,
        edges,
        token_map=token_map,
        artifact_map=artifact_map,
        corpus_weights=corpus_weights,
    )

    groups = [
        build_anchor_group(
            skill,
            skills=skills,
            candidate_skill_names=candidate_map.get(skill_name(skill), set()),
            skill_lookup=skill_lookup,
            token_map=token_map,
            artifact_map=artifact_map,
            verifier_map=verifier_map,
            corpus_weights=corpus_weights,
            undirected_edges=undirected_edges,
            max_group_size=max_group_size,
        )
        for skill in skills
    ]
    group_edges = build_group_edges(groups, edges)
    relation_counts: dict[str, int] = defaultdict(int)
    for edge in group_edges:
        relation_counts[str(edge.get("type", ""))] += 1

    metadata = dict(bundle.get("metadata", {}))
    metadata.update(
        {
            "group_graph_version": GROUP_GRAPH_VERSION,
            "group_count": len(groups),
            "group_edge_count": len(group_edges),
            "group_relation_counts": dict(sorted(relation_counts.items())),
        }
    )
    group_graph = {
        "version": GROUP_GRAPH_VERSION,
        "groups": groups,
        "edges": group_edges,
        "relation_weights": GROUP_RELATION_WEIGHTS,
        "metadata": metadata,
    }
    updated = dict(bundle)
    updated["metadata"] = metadata
    updated["group_graph"] = group_graph
    # Compatibility aliases for scripts that expect group-like bundle keys.
    updated["groups"] = groups
    updated["group_edges"] = group_edges
    return updated


def ensure_group_graph(bundle: dict[str, Any]) -> dict[str, Any]:
    graph = bundle.get("group_graph")
    metadata = dict(bundle.get("metadata", {}))
    if (
        isinstance(graph, dict)
        and int(graph.get("version", 0) or 0) >= GROUP_GRAPH_VERSION
        and graph.get("groups")
        and graph.get("edges") is not None
    ):
        return bundle
    if int(metadata.get("group_graph_version", 0) or 0) >= GROUP_GRAPH_VERSION and bundle.get("groups"):
        updated = dict(bundle)
        updated["group_graph"] = {
            "version": GROUP_GRAPH_VERSION,
            "groups": bundle.get("groups", []),
            "edges": bundle.get("group_edges", []),
            "relation_weights": GROUP_RELATION_WEIGHTS,
            "metadata": metadata,
        }
        return updated
    return build_group_graph(bundle)
