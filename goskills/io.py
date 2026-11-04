"""Versioned JSON and source validation shared by offline and online entry points."""
import json
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import tempfile


def read_json(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def write_json(path, value, *, overwrite=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".goskills-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Atomic fail-if-present, including races.
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_graph(graph):
    if graph.get("schema_version") != 1 or graph.get("kind") != "goskills_graph":
        raise ValueError("Expected a version1 goskills_graph")
    skills = graph.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ValueError("Graph requires a nonempty skill list")
    seen, sources = set(), set()
    for skill in skills:
        for field in ("id", "name", "body", "source_path"):
            if not isinstance(skill.get(field), str) or not skill[field].strip():
                raise ValueError(f"Skill requires nonempty {field}")
        if skill["id"] in seen:
            raise ValueError("Duplicate skill ID")
        if any(char in skill["name"] for char in ("\n", "\r")):
            raise ValueError("Skill display names must be one line")
        seen.add(skill["id"])
        path = PurePosixPath(skill["source_path"])
        if path.is_absolute() or ".." in path.parts or "\n" in str(path):
            raise ValueError("Source paths must be safe library-relative paths")
        if str(path) in sources:
            raise ValueError("Duplicate canonical source path")
        sources.add(str(path))
    valid_types = {"dep", "workflow", "semantic", "alternative", "artifact", "visible-check", "fallback", "incompat"}
    for edge in graph.get("edges", []):
        weight = edge.get("weight")
        if edge.get("source") not in seen or edge.get("target") not in seen:
            raise ValueError("Dangling graph edge")
        if edge.get("type") not in valid_types:
            raise ValueError(f"Unknown edge type: {edge.get('type')}")
        if type(weight) not in (int, float) or not math.isfinite(weight) or weight < 0:
            raise ValueError("Edge weight must be finite and nonnegative")
    return graph


def validate_pool(pool):
    from .config import canonical_hash, validate_config
    if pool.get("schema_version") != 1 or pool.get("kind") not in {"goskill_pool", "goskills_pool"}:
        raise ValueError("Expected a version1 GoSkills group pool")
    integrity = pool.get("integrity", {})
    content = {key: value for key, value in pool.items() if key != "integrity"}
    if integrity.get("content_sha256") != canonical_hash(content):
        raise ValueError("Pool content hash mismatch; rebuild rather than editing frozen artifacts")
    config = validate_config(pool["config"])
    skills, groups = pool["skills"], pool["groups"]
    if not isinstance(skills, dict) or not isinstance(groups, dict) or not groups:
        raise ValueError("Invalid group-pool records")
    validate_graph({"schema_version":1, "kind":"goskills_graph", "skills":list(skills.values()), "edges":[]})
    if any(sid != skill["id"] for sid, skill in skills.items()):
        raise ValueError("Skill ID/key mismatch")
    for gid, group in groups.items():
        members = group["members"]
        if (gid != group["id"] or group["lead"] not in members or len(members) != len(set(members)) or
                not 1 <= len(members) <= config["max_group_size"] or not set(members) <= set(skills)):
            raise ValueError("Invalid group membership")
    policy = pool["provenance"]["policy"]
    if pool["provenance"]["policy_hash"] != canonical_hash(policy) or policy["config"] != config:
        raise ValueError("Group-pool policy mismatch")
    for key, filename in (("groups_source_sha256", "groups.py"), ("facets_source_sha256", "facets.py")):
        if policy.get(key) != hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest():
            raise ValueError("Pool was built with a different offline policy; rebuild it explicitly")
    return pool
