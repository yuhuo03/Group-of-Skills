"""Deterministic, query-independent skill groups and typed group graph.

New reconstruction policy, not recovered GoSkills code. See assumptions A05,
A08, A09 and A17. Canonical ``dep`` is prerequisite -> consumer and workflow
is earlier -> later. Incoming dep/workflow supports are prerequisite /
preprocessor; outgoing ones are dependent / postprocessor. Incoming artifact
supports are parsers, outgoing artifact supports formatters. Visible-check
supports are checkers; semantic supports are generic support. Alternative and
fallback supports are fallbacks. Semantic/alternative edges are symmetric;
other positive edges retain their input direction when lifted between groups.

Explicit metadata exclusivity has two supported forms: ``exclusive_with`` is
a list of exact skill IDs, names or prefixed facets; ``exclusive`` maps a
category to its chosen string/list of strings. Two skills with disjoint chosen
values in the same category conflict. Ordinary tech/format mentions do not.

Group affinity is max(clipped atomic evidence, full positive-facet Jaccard).
Metadata-only artifact/check/support links use the same full-facet Jaccard,
avoiding a weight-one clique merely because many skills mention one format.
Incompatibility is symmetric and suppresses every positive relation for that
group pair. Adjacency is outgoing {gid: [{target, type, weight}, ...]}.
"""
from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import json
from pathlib import Path

from . import facets
from .config import canonical_hash, validate_config
from .io import validate_graph


POLICY_VERSION = "offline-groups-v1"
PRIORITY = {name: rank for rank, name in enumerate(
    ("dep", "workflow", "artifact", "visible-check", "fallback", "alternative", "semantic"))}
SYMMETRIC = {"semantic", "alternative", "incompat"}
LIFT = {"dep": "support", "workflow": "support", "semantic": "support",
        "artifact": "artifact", "visible-check": "visible-check",
        "fallback": "fallback", "alternative": "fallback", "incompat": "incompatibility"}


def _norm(value):
    return " ".join(str(value).casefold().split())


def _strings(value, label):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{label} must be a string or list of nonempty strings")
    return {_norm(x) for x in value}


def _exclusive(skill):
    metadata = skill.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Skill metadata must be an object")
    selected = metadata.get("exclusive", {})
    if not isinstance(selected, dict):
        raise ValueError("metadata.exclusive must map category to chosen values")
    return {_norm(k): _strings(v, "metadata.exclusive values") for k, v in selected.items()}


def _positive(skill):
    return {_norm(x) for x in skill["facets"]} | {_norm(skill["id"]), _norm(skill["name"])}


def _conflict(left, right):
    if right["id"] in left.get("incompatible_ids", []) or left["id"] in right.get("incompatible_ids", []):
        return True
    if ({_norm(x) for x in left["negative"]} & _positive(right)
            or {_norm(x) for x in right["negative"]} & _positive(left)):
        return True
    for own, other in ((left, right), (right, left)):
        blocked = _strings(own.get("metadata", {}).get("exclusive_with", []), "metadata.exclusive_with")
        if blocked & _positive(other):
            return True
    a, b = _exclusive(left), _exclusive(right)
    return any(a[key] and b[key] and a[key].isdisjoint(b[key]) for key in a.keys() & b.keys())


def compatible_members(member_ids, skills):
    """Shared offline/online compatibility; exact negative/exclusive evidence only.

    ``skills`` is the pool's enriched ID dictionary. Input atomic incompat edges
    are retained as ``incompatible_ids`` so this check also works during online
    group expansion/backfill without access to the original graph.
    """
    ids = sorted(set(member_ids))
    if any(sid not in skills for sid in ids):
        raise ValueError("Compatibility references an unknown skill")
    return all(not _conflict(skills[a], skills[b]) for a, b in combinations(ids, 2))


def _role(lead, edge):
    incoming = edge["target"] == lead
    kind = edge["type"]
    if kind == "dep":
        return "prerequisite" if incoming else "dependent"
    if kind == "workflow":
        return "preprocessor" if incoming else "postprocessor"
    if kind == "artifact":
        return "parser" if incoming else "formatter"
    if kind == "visible-check":
        return "checker"
    if kind in {"alternative", "fallback"}:
        return "fallback"
    return "support"


def _union(skills, members, field):
    return set().union(*(set(skills[sid][field]) for sid in members))


def _triple_adds(lead, supports, roles, skills):
    # The second support must add role/artifact/check beyond lead + first pair.
    first, second = supports
    if roles[second] not in {roles[lead], roles[first]}:
        return True
    return any(set(skills[second][field]) - _union(skills, [lead, first], field)
               for field in ("artifacts", "checks"))


def _jaccard(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _similar_pairs(groups, threshold):
    """Exact Jaccard candidate join via rare-first inverted prefixes.

    If Jaccard(A,B)>=t, prefixes of length |A|-ceil(t|A|)+1 and
    |B|-ceil(t|B|)+1 share a token under the same global order. We use the
    conservative floor-based equivalent, then check the actual similarity.
    No full group-by-group scan or approximate neighbor cap is used.
    """
    frequencies = Counter(f for g in groups.values() for f in g["facets"])
    index = defaultdict(list)
    for gid, group in sorted(groups.items()):
        terms = sorted(set(group["facets"]), key=lambda x: (frequencies[x], x))
        length = len(terms)
        if not length:
            continue
        # One extra token is conservative at integral boundaries.
        prefix = terms[:min(length, length - int(threshold * length) + 1)]
        candidates = set()
        for term in prefix:
            candidates.update(index[term])
        for other in sorted(candidates):
            other_length = len(groups[other]["facets"])
            if threshold and min(length, other_length) < threshold * max(length, other_length):
                continue
            weight = _jaccard(set(terms), set(groups[other]["facets"]))
            if weight > 0 and weight >= threshold:
                yield other, gid, weight
        for term in prefix:
            index[term].append(gid)


def _conflicting_skill_pairs(skills, edges):
    positives = defaultdict(set)
    exclusive = defaultdict(set)
    candidates = set()
    for sid, skill in skills.items():
        for term in _positive(skill):
            positives[term].add(sid)
        for key in _exclusive(skill):
            exclusive[key].add(sid)
    for sid, skill in skills.items():
        terms = {_norm(x) for x in skill["negative"]}
        terms |= _strings(skill.get("metadata", {}).get("exclusive_with", []), "metadata.exclusive_with")
        for term in terms:
            candidates.update(tuple(sorted((sid, other))) for other in positives[term] if other != sid)
    for bucket in exclusive.values():
        candidates.update(combinations(sorted(bucket), 2))
    for edge in edges:
        if edge["type"] == "incompat" and edge["source"] != edge["target"]:
            candidates.add(tuple(sorted((edge["source"], edge["target"]))))
    return sorted(pair for pair in candidates if _conflict(*(skills[sid] for sid in pair)))


def build_pool(graph: dict, config: dict) -> dict:
    """Build version1 JSON-safe pool, preserving source/config/policy hashes.

    This function performs no I/O except reading its own policy module bytes for
    provenance. It does not query an LLM, mutate graph/config, or read task data.
    """
    validate_graph(graph)
    config = validate_config(config)
    skills = {}
    for skill in sorted(graph["skills"], key=lambda s: s["id"]):
        # JSON roundtrip gives independent retained metadata/source records.
        enriched = facets.enrich_skill(json.loads(json.dumps(skill, allow_nan=False)))
        enriched["incompatible_ids"] = []
        _exclusive(enriched)
        _strings(enriched.get("metadata", {}).get("exclusive_with", []), "metadata.exclusive_with")
        skills[skill["id"]] = enriched
    edge_map = {}
    for edge in graph.get("edges", []):
        key = edge["source"], edge["target"], edge["type"]
        if key not in edge_map or edge["weight"] > edge_map[key]["weight"]:
            edge_map[key] = {k: edge[k] for k in ("source", "target", "type", "weight")}
    edges = [edge_map[key] for key in sorted(edge_map)]
    touching, incident = defaultdict(list), defaultdict(list)
    for edge in edges:
        incident[edge["source"]].append(edge)
        if edge["source"] != edge["target"]:
            incident[edge["target"]].append(edge)
        if edge["type"] == "incompat":
            skills[edge["source"]]["incompatible_ids"].append(edge["target"])
            skills[edge["target"]]["incompatible_ids"].append(edge["source"])
        elif edge["weight"] > 0 and edge["source"] != edge["target"]:
            touching[edge["source"]].append(edge)
            touching[edge["target"]].append(edge)
    for skill in skills.values():
        skill["incompatible_ids"] = sorted(set(skill["incompatible_ids"]))

    groups = {}
    for lead in skills:
        best_neighbors = {}
        for edge in touching[lead]:
            neighbor = edge["target"] if edge["source"] == lead else edge["source"]
            rank = (PRIORITY[edge["type"]], -edge["weight"], neighbor,
                    edge["source"], edge["target"])
            if neighbor not in best_neighbors or rank < best_neighbors[neighbor][0]:
                best_neighbors[neighbor] = rank, edge
        ordered = sorted(best_neighbors, key=lambda sid: best_neighbors[sid][0])[:config["neighbor_limit"]]
        for count in range(min(config["max_group_size"] - 1, len(ordered)) + 1):
            for supports in combinations(ordered, count):
                members = [lead] + list(supports)
                if not compatible_members(members, skills):
                    continue
                roles = {lead: "anchor", **{sid: _role(lead, best_neighbors[sid][1]) for sid in supports}}
                if count == 2 and not _triple_adds(lead, supports, roles, skills):
                    continue
                internal = {(e["source"], e["target"], e["type"]): e
                            for sid in members for e in incident[sid]
                            if e["source"] in members and e["target"] in members}
                topology = [dict(internal[key]) for key in sorted(internal)]
                positive = [e["weight"] for e in topology if e["type"] != "incompat" and e["weight"] > 0]
                prior = sum(positive) / len(positive) if positive else 0.0
                required = set(skills[lead]["facets"])
                all_facets = _union(skills, members, "facets")
                gid = "g_" + canonical_hash([lead, sorted(members)])
                group = {"id": gid, "lead": lead, "members": [lead] + sorted(supports),
                         "roles": roles, "required": sorted(required),
                         "optional": sorted(all_facets - required), "facets": sorted(all_facets),
                         "negative": sorted(_union(skills, members, "negative")),
                         "anchors": sorted(_union(skills, members, "anchors")),
                         "artifacts": sorted(_union(skills, members, "artifacts")),
                         "checks": sorted(_union(skills, members, "checks")),
                         "prior": prior, "topology": topology}
                if gid not in groups or prior > groups[gid]["prior"]:
                    groups[gid] = group
    groups = dict(sorted(groups.items()))
    member_index, facet_index = defaultdict(list), defaultdict(list)
    for gid, group in groups.items():
        for sid in group["members"]:
            member_index[sid].append(gid)
        for facet in group["facets"]:
            facet_index[facet].append(gid)

    incompatible_groups = set()
    for source, target in _conflicting_skill_pairs(skills, edges):
        for left in member_index[source]:
            for right in member_index[target]:
                if left != right:
                    incompatible_groups.add(tuple(sorted((left, right))))
    group_edge_map = {}

    def add(source, target, kind, weight):
        if source == target or weight <= 0:
            return
        if kind != "incompatibility" and tuple(sorted((source, target))) in incompatible_groups:
            return
        weight = min(1.0, float(weight))
        if kind != "incompatibility" and weight < config["affinity_threshold"]:
            return
        key = source, target, kind
        group_edge_map[key] = max(group_edge_map.get(key, 0.0), weight)

    for left, right in sorted(incompatible_groups):
        add(left, right, "incompatibility", 1.0)
        add(right, left, "incompatibility", 1.0)
    for edge in edges:
        if edge["type"] == "incompat" or edge["weight"] <= 0:
            continue
        for source in member_index[edge["source"]]:
            for target in member_index[edge["target"]]:
                affinity = max(min(1.0, edge["weight"]), _jaccard(set(groups[source]["facets"]), set(groups[target]["facets"])))
                add(source, target, LIFT[edge["type"]], affinity)
                if edge["type"] in SYMMETRIC:
                    add(target, source, LIFT[edge["type"]], affinity)
    for source, target, weight in _similar_pairs(groups, config["affinity_threshold"]):
        kinds = ["support"]
        if set(groups[source]["artifacts"]) & set(groups[target]["artifacts"]):
            kinds.append("artifact")
        if set(groups[source]["checks"]) & set(groups[target]["checks"]):
            kinds.append("visible-check")
        for kind in kinds:
            add(source, target, kind, weight)
            add(target, source, kind, weight)
    group_edges = [{"source": source, "target": target, "type": kind, "weight": weight}
                   for (source, target, kind), weight in sorted(group_edge_map.items())]
    adjacency = {gid: [] for gid in groups}
    for edge in group_edges:
        adjacency[edge["source"]].append({k: edge[k] for k in ("target", "type", "weight")})
    module_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    facets_hash = hashlib.sha256(Path(facets.__file__).read_bytes()).hexdigest()
    policy = {"version": POLICY_VERSION, "config": config,
              "groups_source_sha256": module_hash, "facets_source_sha256": facets_hash}
    pool = {"schema_version": 1, "kind": "goskill_pool", "config": config,
            "provenance": {"source_graph_hash": canonical_hash(graph), "policy": policy,
                           "policy_hash": canonical_hash(policy),
                           "source_provenance": graph.get("provenance", {})},
            "skills": skills, "groups": groups, "group_edges": group_edges,
            "member_index": dict(sorted(member_index.items())),
            "facet_index": dict(sorted(facet_index.items())), "adjacency": adjacency}
    pool["integrity"] = {"content_sha256": canonical_hash(pool)}
    return pool
