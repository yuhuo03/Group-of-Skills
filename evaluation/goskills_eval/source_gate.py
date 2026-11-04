"""Read-only source fidelity checks for the isolated complete-groups cohort.

The ordinary bundle validator checks budgets and rendered coverage. This gate
additionally checks the actual immutable pool, including extractive offsets.
It never executes skills, reads rewards or reconstructs absent source content.
"""

METHOD = "goskills-paper-complete-groups-v3"


def validate_frozen_sources(bundle, pool, pool_hash, source_root="/opt/graphskills/skills"):
    def require(condition, reason):
        if not condition:
            raise ValueError(reason)

    require(bundle.get("method") == METHOD, "wrong_method")
    require(bundle.get("pool_hash") == pool_hash, "wrong_pool")
    require(bundle.get("config") == pool["config"], "wrong_config")
    require(bundle.get("provenance") == pool.get("provenance", {}), "wrong_provenance")
    limit = pool["config"]["max_skill_chars"]
    ids = [s["id"] for s in bundle["presented_skills"]]
    require(len(ids) == len(set(ids)), "duplicate_payload")
    for skill in bundle["presented_skills"]:
        original = pool["skills"].get(skill["id"])
        require(original is not None, "unknown_skill")
        require(skill["name"] == original["name"], "wrong_skill_name")
        require(skill["source_path"] == source_root.rstrip("/") + "/" + original["source_path"], "wrong_source_path")
        source, spans = original["body"], skill.get("source_spans")
        require(not source.strip() or bool(skill["body"].strip()), "empty_presented_source")
        require(isinstance(spans, list), "missing_source_spans")
        previous_end = 0
        for span in spans:
            require(isinstance(span, list) and len(span) == 2 and
                    all(type(x) is int for x in span), "malformed_source_span")
            start, end = span
            require(previous_end <= start <= end <= len(source), "invalid_source_span_bounds")
            require(start < end or not source and spans == [[0, 0]], "empty_source_span")
            previous_end = end
        expected = "\n\n".join(source[start:end] for start, end in spans)
        require(skill["body"] == expected and len(expected) <= limit, "source_content_mismatch")
        require(skill.get("body_truncated") is (expected != source), "wrong_truncation_disclosure")
        policy = skill.get("presentation_policy")
        require(policy in {"extractive-source-spans", "prefix-preserve-explicit-facets", "prefix-preserve-procedural-scope"}, "wrong_presentation_policy")
        if policy in {"prefix-preserve-explicit-facets", "prefix-preserve-procedural-scope"}:
            prefix = source[:limit]
            require(expected == prefix and spans == [[0, len(prefix)]], "false_prefix_fallback")

    union = set()
    for detail in bundle["plan_details"]:
        group = pool["groups"].get(detail["id"])
        require(group is not None and all(detail[key] == group[key] for key in ("lead", "members", "roles")), "wrong_group_plan")
        require(group["lead"] in ids, "missing_group_lead")
        union.update(group["members"])
    trace = bundle["trace"]
    require(all(s["id"] in union for s in trace["skill_steps"]), "bottleneck_outside_plan")
    require(set(trace["reserved_members"]) <= set(ids), "missing_reserved_member")
    backfilled = {s["id"] for s in trace["backfill_steps"]}
    require(set(ids) <= union | backfilled, "unaccounted_payload")
    return {"status": "PASSED", "method": METHOD, "skills": len(ids),
            "source_span_fidelity": True, "original_raw_unchanged": True}
