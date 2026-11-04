"""Independent output checks; no reward or method ranking is used."""
from .config import validate_config
from .facets import extract, all_facets


def validate_bundle(bundle):
    if bundle.get("schema_version") != 1 or bundle.get("kind") != "goskills_bundle":
        raise ValueError("Unsupported retrieval bundle")
    config = validate_config(bundle["config"])
    payloads = bundle["presented_skills"]
    ids = [item["id"] for item in payloads]
    if len(ids) != len(set(ids)) or len(ids) > config["top_n"]:
        raise ValueError("Duplicate or over-budget payloads")
    rendered = bundle["rendered_context"]
    if len(rendered) > config["max_context_chars"] or len(rendered) != bundle["rendered_chars"]:
        raise ValueError("Context budget mismatch")
    positions = [rendered.find(field + "\n") for field in ("START", "SUPPORT", "CHECK", "AVOID", "SKILLS", "DEBT")]
    if min(positions) < 0 or positions != sorted(positions) or len(set(positions)) != 6:
        raise ValueError("Missing or reordered contract sections")
    details = bundle["plan_details"]
    if [item["id"] for item in details] != bundle["plan"]:
        raise ValueError("Plan details disagree with selected group IDs")
    if any(item["lead"] not in item["members"] or not set(item["members"]) & set(ids) for item in details):
        raise ValueError("Plan contains a malformed or unrepresented group")
    anchor = next((item["lead"] for item in details if item["lead"] in ids), None)
    if anchor != bundle["anchor_skill_id"]:
        raise ValueError("Anchor is not the first presented lead")
    names = {item["id"]:item["name"] for item in payloads}
    expected_start = (f"START\nUse {names[anchor]} first because its group matches the visible task evidence.\n"
                      "Inspect its source path before writing new code.\n" if anchor else
                      "START\nNo eligible anchor fits this query and budget. Solve using the visible task requirements.\n")
    if not rendered.startswith(expected_start):
        raise ValueError("Rendered START names an unpresented or incorrect anchor")
    covered = set()
    for item in payloads:
        body = item["body"]
        expected = f"Skill: {item['name']}\nSource: {item['source_path']}\n\n{body}"
        if len(body) > config["max_skill_chars"] or len(body) != item["body_chars"]:
            raise ValueError("Payload body budget mismatch")
        if expected != item["rendered"] or expected not in rendered:
            raise ValueError("Claimed payload absent from actual context")
        covered |= all_facets(extract(item["name"] + "\n" + body))
    debt = sorted(set(bundle["schema"]["high_confidence"]) - covered)
    if debt != bundle["coverage_debt"]:
        raise ValueError("Coverage debt disagrees with visible payloads")
    debt_text = "\nDEBT\n" + ("\n".join("- " + item for item in debt) if debt else "None.") + "\n"
    if not rendered.endswith(debt_text):
        raise ValueError("Rendered DEBT field disagrees with accounted coverage debt")
    if len(bundle["plan"]) > config["max_groups"]:
        raise ValueError("Group plan exceeds budget")
    backfill = bundle["trace"]["backfill_steps"]
    if len(backfill) > config["backfill_cap"]:
        raise ValueError("Backfill exceeds cap")
    if not set(ids) <= set(bundle["activated_skill_ids"]):
        raise ValueError("Presented skill outside activated universe")
    if any(step["id"] not in ids or not step["covered_debt"] for step in backfill):
        raise ValueError("Invalid backfill evidence")
    return {"status": "passed", "presented_skills": len(ids), "groups": len(bundle["plan"]),
            "rendered_chars": len(rendered), "remaining_debt": len(debt)}
