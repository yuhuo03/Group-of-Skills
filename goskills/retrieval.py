"""Deterministic online group policy, with every selection and debt change logged."""
from __future__ import annotations

from collections import Counter
import copy
import math
from pathlib import PurePosixPath

from .config import FEATURES, WEIGHTS, canonical_hash, validate_config
from .facets import all_facets, extract, tokens
from .io import validate_pool
from .presentation import extractive_body


def clip(value):
    return min(1.0, max(0.0, float(value)))


def fraction(covered, requested):
    return len(set(covered) & set(requested)) / len(requested) if requested else 0.0


def weighted(stage, values):
    features = {key: clip(values.get(key, 0)) for key in FEATURES}
    return sum(weight * features[key] for key, weight in zip(FEATURES, WEIGHTS[stage])), features


def lexical_seeds(skills, query, count):
    """Binary TF-IDF cosine over public skill text; no outcome-derived weights.

    Original overlap normalized by query length rewards arbitrarily long skill
    documents. Cosine normalizes both vectors. Separator normalization is limited
    to retrieval aliases; it does not alter schema, skill text, or requirements.
    """
    def terms(text):
        return tokens(text.replace("-", " ").replace("_", " "))
    query_terms = terms(query)
    documents = {sid: terms(" ".join((skill["name"], skill.get("description", ""),
                                    skill.get("text", skill["body"]))))
                 for sid, skill in skills.items()}
    frequency = Counter(term for document in documents.values() for term in document)
    n = len(documents)
    idf = {term: 1 + math.log((1 + n) / (1 + frequency.get(term, 0)))
           for term in set(frequency) | query_terms}
    query_norm = math.sqrt(math.fsum(idf[t] ** 2 for t in sorted(query_terms)))
    scores = {}
    for sid, document in documents.items():
        overlap = query_terms & document
        if not overlap or not query_norm:
            continue
        doc_norm = math.sqrt(math.fsum(idf[t] ** 2 for t in sorted(document)))
        scores[sid] = math.fsum(idf[t] ** 2 for t in sorted(overlap)) / (query_norm * doc_norm)
    ranked = sorted(scores, key=lambda sid: (-scores[sid], sid))[:count]
    maximum = max((scores[sid] for sid in ranked), default=1)
    return [{"id": sid, "score": scores[sid] / maximum, "rank": rank + 1,
             "source": "lexical-tfidf-cosine-separators-v1"} for rank, sid in enumerate(ranked)]


class Retriever:
    def __init__(self, pool, *, source_root=None):
        validate_pool(pool)
        self.pool = copy.deepcopy(pool)
        pool = self.pool
        self.config = validate_config(pool["config"])
        self.skills = pool["skills"]
        self.groups = pool["groups"]
        self.source_root = source_root.rstrip("/") if source_root else None
        if self.source_root and any(x in self.source_root for x in ("\n", "\r")):
            raise ValueError("Source root cannot contain line breaks")
        self.payloads = {}
        self.visible_facets = {}
        for sid, skill in self.skills.items():
            body = skill["body"][:self.config["max_skill_chars"]]
            source = skill["source_path"]
            if self.source_root:
                source = self.source_root + "/" + str(PurePosixPath(source))
            self.payloads[sid] = {"id": sid, "name": skill["name"], "source_path": source,
                                  "body": body, "body_chars": len(body),
                                  "rendered": f"Skill: {skill['name']}\nSource: {source}\n\n{body}",
                                  "body_truncated": len(body) < len(skill["body"])}
            # Coverage is not credited for hidden metadata or truncated-away text.
            visible = extract(skill["name"] + "\n" + body)
            self.visible_facets[sid] = all_facets(visible)

        self._prefix_payloads = copy.deepcopy(self.payloads)
        self._prefix_visible_facets = dict(self.visible_facets)

    def _prepare_payloads(self, text, selected, schema):
        limit = self.config["max_skill_chars"]
        for sid in selected:
            skill = self.skills[sid]
            body, spans = extractive_body(skill["body"], text, self.config["max_skill_chars"])
            visible = all_facets(extract(skill["name"] + "\n" + body))
            previous = self._prefix_visible_facets[sid] & set(schema["high_confidence"])
            policy = "prefix-preserve-procedural-scope" if len(skill["body"]) > limit and spans == [[0, limit]] else "extractive-source-spans"
            if not previous <= visible:
                body = self._prefix_payloads[sid]["body"]
                spans = [[0, len(body)]]
                policy = "prefix-preserve-explicit-facets"
            payload = self.payloads[sid]
            payload["presentation_policy"] = policy
            payload.update(body=body, body_chars=len(body), source_spans=spans,
                           body_truncated=body != skill["body"],
                           rendered=f"Skill: {skill['name']}\nSource: {payload['source_path']}\n\n{body}")
            self.visible_facets[sid] = all_facets(extract(skill["name"] + "\n" + body))

    def _reserved(self, plan):
        """Leads first, then explicit incoming prerequisite/preprocessor members."""
        reserved = list(dict.fromkeys(self.groups[gid]["lead"] for gid in plan))
        for gid in plan:
            group = self.groups[gid]
            for sid in sorted(group["members"]):
                incoming = any(edge["source"] == sid and edge["target"] == group["lead"]
                               and edge.get("type") in {"dep", "workflow"}
                               and edge.get("weight", 0) > 0 for edge in group.get("topology", []))
                if (sid not in reserved and incoming
                    and self._query_relevance.get(sid, 0) > 0
                    and group["roles"].get(sid) in {"prerequisite", "preprocessor"}):
                    reserved.append(sid)
        return reserved

    def _plan_fits(self, plan, schema):
        reserved = self._reserved(plan)
        return (all(self._eligible(self.skills[sid], schema) for sid in reserved)
                and self._compatible(reserved) and self._fits(plan, reserved, schema))

    def _eligible(self, item, schema):
        return not (set(item.get("negative", [])) & set(schema["high_confidence"]) or
                    set(item.get("anchors", [])) & set(schema["negative"]))

    def _compatible(self, ids):
        from .groups import compatible_members
        return compatible_members(list(dict.fromkeys(ids)), self.skills)

    def _union(self, ids, field="facets"):
        return set().union(*(set(self.skills[sid].get(field, [])) for sid in ids)) if ids else set()

    def _debt(self, selected, schema):
        covered = set().union(*(self.visible_facets[sid] for sid in selected)) if selected else set()
        return sorted(set(schema["high_confidence"]) - covered)

    def _roles(self, plan, selected):
        roles = {}
        for gid in plan:
            group = self.groups[gid]
            for sid in selected:
                if sid in group["members"]:
                    role = group["roles"].get(sid, "support")
                    if sid == group["lead"] and gid != plan[0]:
                        role = "support lead"
                    roles.setdefault(sid, role)
        for sid in selected:
            roles.setdefault(sid, "coverage support")
        return roles

    def _render(self, plan, selected, schema):
        debt = self._debt(selected, schema)
        anchor = next((self.groups[gid]["lead"] for gid in plan if self.groups[gid]["lead"] in selected), None)
        roles = self._roles(plan, selected)
        fields = ["START"]
        if anchor:
            fields += [f"Use {self.skills[anchor]['name']} first because its group matches the visible task evidence.",
                       "Inspect its source path before writing new code."]
        else:
            fields += ["No eligible anchor fits this query and budget. Solve using the visible task requirements."]
        fields += ["", "SUPPORT", "Use these skills only for the stated roles:"]
        supports = [sid for sid in selected if sid != anchor]
        fields += [f"- {self.skills[sid]['name']}: {roles[sid]} — supports the selected plan or an explicit requirement."
                   for sid in supports] or ["None."]
        checks = sorted(set(schema["check"] + schema["artifact"] + schema["constraint"]))
        fields += ["", "CHECK", "Before finalizing, verify these visible requirements:"]
        fields += ["- " + item for item in checks] or ["Follow the explicit task requirements."]
        negatives = sorted(set(schema["negative"]) | self._union(selected, "negative"))
        fields += ["", "AVOID", "Do not follow these incompatible interpretations:"]
        fields += ["- " + item for item in negatives] or ["None identified from explicit applicability cues."]
        fields += ["", "SKILLS"]
        fields += [self.payloads[sid]["rendered"] for sid in selected] or ["None."]
        fields += ["", "DEBT"]
        fields += ["- " + item for item in debt] or ["None."]
        return "\n".join(fields) + "\n"

    def _fits(self, plan, selected, schema):
        return len(selected) <= self.config["top_n"] and len(self._render(plan, selected, schema)) <= self.config["max_context_chars"]

    def _group_features(self, group, schema, relevance, selected_members=()):
        covered = self._union(selected_members)
        group_facets = set(group["facets"])
        query_facets = all_facets(schema)
        novel = group_facets - covered if selected_members else group_facets
        anchors = set(schema["tech"] + schema["artifact"])
        check = set(schema["check"] + schema["artifact"] + schema["constraint"])
        members = group["members"]
        eligible_members = [sid for sid in members if sid not in selected_members]
        lead_anchors = set(self.skills[group["lead"]].get("anchors", []))
        exact_anchor = bool(lead_anchors & set(schema["high_confidence"]) & anchors)
        alias_anchor = bool(lead_anchors & anchors)
        edge_weights = [edge.get("weight", 0) for edge in group.get("topology", []) if edge.get("type") != "incompat"]
        return {"relevance": max((relevance.get(sid, 0) for sid in eligible_members), default=0),
                "coverage": fraction(novel, query_facets),
                "anchor": 1.0 if exact_anchor else .7 if alias_anchor else 0,
                "check": fraction(novel, check), "connectivity": sum(edge_weights),
                "redundancy": fraction(covered, group_facets) if selected_members else 0,
                "negative": float(not self._eligible(group, schema)),
                "cost": sum(len(self.payloads[sid]["rendered"]) for sid in eligible_members) / self.config["max_context_chars"]}

    def _support_evidence(self, group, schema, relevance, selected_members, selected_leads=()):
        """Ground each additional mandatory lead in public query evidence.

        A lifted group edge alone is insufficient. Preserve prerequisites with
        a positive directed dep/workflow edge to a query-grounded member.
        This is an explicit completion of the paper's GroupNeighbors operator.
        """
        selected = set(selected_members)
        # A shared file extension or generic constraint is not domain/operation
        # evidence for admitting an extra mandatory lead. Artifact debt remains.
        query_facets = set().union(*(set(schema[k]) for k in
                                    ('tech', 'op', 'failure', 'check')))
        covered = set().union(*(self.visible_facets[sid] for sid in selected)) if selected else set()
        novel = {sid: sorted((self.visible_facets[sid] & query_facets) - covered)
                 for sid in group["members"] if sid not in selected}
        def reasons(sid):
            result = []
            if relevance.get(sid, 0) > 0:
                result.append({"kind": "query_seed", "id": sid})
            if novel.get(sid):
                result.append({"kind": "visible_query_gain", "id": sid, "facets": novel[sid]})
            for edge in group.get("topology", []):
                target = edge["target"]
                if (edge["source"] == sid and target != sid and target in group["members"]
                    and edge["type"] in {"dep", "workflow"} and edge.get("weight", 0) > 0
                    and (relevance.get(target, 0) > 0 or novel.get(target))):
                    result.append({"kind": "typed_predecessor", "id": sid,
                                   "target": target, "type": edge["type"]})
            return result
        lead = group["lead"]
        if lead not in set(selected_leads):
            return reasons(lead)
        return [reason for sid in group["members"] if sid not in selected for reason in reasons(sid)]

    def _skill_features(self, sid, selected, plan, schema, relevance):
        skill = self.skills[sid]
        covered = self._union(selected)
        novel = set(skill["facets"]) - covered
        anchors = set(schema["tech"] + schema["artifact"])
        check = set(schema["check"] + schema["artifact"] + schema["constraint"])
        connections = [edge.get("weight", 0) for gid in plan for edge in self.groups[gid].get("topology", [])
                       if edge.get("type") != "incompat" and
                       ((edge["source"] == sid and edge["target"] in selected) or
                        (edge["target"] == sid and edge["source"] in selected))]
        return {"relevance": relevance.get(sid, 0), "coverage": fraction(novel, all_facets(schema)),
                "anchor": 1 if set(skill["anchors"]) & anchors & set(schema["high_confidence"]) else
                          .7 if set(skill["anchors"]) & anchors else 0,
                "check": fraction(novel, check), "connectivity": sum(connections),
                "redundancy": fraction(covered, skill["facets"]),
                "negative": float(not self._eligible(skill, schema)),
                "cost": len(self.payloads[sid]["rendered"]) / self.config["max_context_chars"]}

    def query(self, query, *, public_context="", seeds=None):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must contain explicit public task text")
        if not isinstance(public_context, str):
            raise TypeError("public_context must be explicitly supplied text")
        text = query + ("\n\n" + public_context if public_context else "")
        self.payloads = copy.deepcopy(self._prefix_payloads)
        self.visible_facets = dict(self._prefix_visible_facets)
        schema = extract(text)
        if not self._fits([], [], schema):
            raise ValueError("Visible requirements/debt alone exceed context budget; no silent truncation")
        if self.config["seed_mode"] == "external":
            if seeds is None:
                raise ValueError("External seed mode requires explicit scored evidence with provenance")
            evidence = []
            for rank, seed in enumerate(seeds):
                if (seed.get("id") not in self.skills or not isinstance(seed.get("source"), str) or
                    not seed["source"] or type(seed.get("score")) not in (int, float) or
                    not math.isfinite(seed["score"]) or seed["score"] < 0):
                    raise ValueError("Malformed external seed evidence")
                evidence.append({**seed, "rank": rank + 1})
            if len({seed["id"] for seed in evidence}) != len(evidence):
                raise ValueError("Duplicate external seed IDs")
            evidence = evidence[:self.config["seed_top_k"]]
        else:
            if seeds is not None:
                raise ValueError("External seeds supplied while configuration says lexical")
            evidence = lexical_seeds(self.skills, text, self.config["seed_top_k"])
        maximum = max((seed["score"] for seed in evidence), default=0) or 1
        relevance = {seed["id"]: seed["score"] / maximum for seed in evidence}
        self._query_relevance = relevance
        seed_rank = {seed["id"]: seed["rank"] for seed in evidence}
        candidate_ids = set()
        for facet in all_facets(schema):
            candidate_ids.update(self.pool["facet_index"].get(facet, []))
        for sid in relevance:
            candidate_ids.update(self.pool["member_index"].get(sid, []))
        candidate_ids = {gid for gid in candidate_ids if self._eligible(self.groups[gid], schema)}
        activated = set(relevance)
        activated.update(sid for gid in candidate_ids for sid in self.groups[gid]["members"])
        trace = {"candidate_count": len(candidate_ids), "group_scores": {}, "support_steps": [],
                 "skill_steps": [], "backfill_steps": [], "support_eligibility": [], "budget_rejections": [], "pruned_groups": []}
        scores = {}
        for gid in sorted(candidate_ids):
            score, features = weighted("group", self._group_features(self.groups[gid], schema, relevance))
            score += self.config["lambda_prior"] * clip(self.groups[gid]["prior"])
            scores[gid] = score
            trace["group_scores"][gid] = {"score": score, "features": features}
        def tie(gid):
            return (seed_rank.get(self.groups[gid]["lead"], 10**9), len(self.groups[gid]["members"]), gid)
        ranked = sorted(candidate_ids, key=lambda gid: (-scores[gid], *tie(gid)))
        seed_values = sorted(relevance.values(), reverse=True)
        gap = seed_values[0] - seed_values[1] if len(seed_values) > 1 else 1.0
        spread = max(seed_values) - min(seed_values) if len(seed_values) > 1 else 1.0
        ambiguity = .55 * (1 - clip(gap)) + .45 * (1 - clip(spread))
        complexity = sum(bool(schema[key]) for key in ("core", "tech", "op", "artifact", "constraint", "failure", "check")) / 7
        difficulty = .60 * complexity + .40 * ambiguity
        limit = min(32, math.ceil(max(6, 2 * self.config["top_n"]) + 1 + 2 * difficulty))
        floor = max(.10, .55 - .30 * difficulty) * max((scores[gid] for gid in ranked), default=0)
        minimum = min(limit, math.ceil(3 + 3 * difficulty))
        shortlist = [gid for index, gid in enumerate(ranked[:limit]) if scores[gid] >= floor or index < minimum]
        trace["adaptive_pool"] = dict(complexity=complexity, ambiguity=ambiguity, difficulty=difficulty,
                                      limit=limit, floor=floor, minimum=minimum, shortlist=shortlist)
        corrected = {gid: scores[gid] + self.config["lambda_anchor"] * trace["group_scores"][gid]["features"]["anchor"]
                     for gid in shortlist}
        plausible = [gid for gid in shortlist if corrected[gid] >= self.config["group_min"] and
                     self._eligible(self.skills[self.groups[gid]["lead"]], schema) and
                     self._plan_fits([gid], schema)]
        specific = [gid for gid in plausible if trace["group_scores"][gid]["features"]["anchor"] > 0]
        anchor = min(specific or plausible, key=lambda gid: (-corrected[gid], *tie(gid))) if plausible else None
        plan = [anchor] if anchor else []
        trace["anchor"] = {"selected": anchor, "corrected_scores": corrected,
                           "specific_preference": bool(specific)}
        while plan and len(plan) < self.config["max_groups"]:
            members = list(dict.fromkeys(sid for gid in plan for sid in self.groups[gid]["members"]))
            options = set(shortlist) - set(plan)
            graph_weights = {}
            for selected_gid in plan:
                for edge in self.pool["adjacency"].get(selected_gid, []):
                    if edge["type"] not in {"incompat", "incompatibility"} and edge["weight"] > 0 and edge["target"] not in plan:
                        options.add(edge["target"])
                        graph_weights[edge["target"]] = max(graph_weights.get(edge["target"], 0), edge["weight"])
            candidates = []
            for gid in sorted(options):
                group = self.groups[gid]
                if not self._eligible(group, schema) or not self._compatible(members + group["members"]):
                    continue
                support_evidence = self._support_evidence(group, schema, relevance, members, [self.groups[x]["lead"] for x in plan])
                trace["support_eligibility"].append({"group": gid, "plan": list(plan),
                                                     "accepted": bool(support_evidence),
                                                     "evidence": support_evidence})
                if not support_evidence:
                    continue
                values = self._group_features(group, schema, relevance, members)
                values["connectivity"] = max(values["connectivity"], graph_weights.get(gid, 0))
                # A repeated internal edge is not new support for the current plan.
                novel = bool((set(group["facets"]) - self._union(members)) & all_facets(schema))
                if not novel and not (graph_weights.get(gid, 0) > 0 and set(group["members"]) - set(members)):
                    continue
                score, features = weighted("support", values)
                if score < self.config["support_min"]:
                    continue
                if not self._plan_fits(plan + [gid], schema):
                    trace["budget_rejections"].append({"stage": "support", "id": gid})
                    continue
                candidates.append((score, gid, features))
            if not candidates:
                break
            score, gid, features = min(candidates, key=lambda row: (-row[0], *tie(row[1])))
            plan.append(gid)
            activated.update(self.groups[gid]["members"])
            trace["support_steps"].append({"group": gid, "score": score, "features": features})
        selected = []
        for gid in plan:
            sid = self.groups[gid]["lead"]
            if sid not in selected and self._eligible(self.skills[sid], schema) and self._compatible(selected + [sid]) and self._fits(plan, selected + [sid], schema):
                selected.append(sid)
                trace["skill_steps"].append({"id": sid, "stage": "insert_lead", "group": gid})
        trace["reserved_members"] = self._reserved(plan)
        for sid in trace["reserved_members"]:
            if sid not in selected:
                if not self._fits(plan, selected + [sid], schema):
                    raise RuntimeError("Reserved dependency lost after group feasibility check")
                selected.append(sid)
                trace["skill_steps"].append({"id": sid, "stage": "insert_prerequisite"})
        union = {sid for gid in plan for sid in self.groups[gid]["members"]}
        while len(selected) < self.config["top_n"]:
            options = []
            for sid in sorted((union & activated) - set(selected)):
                if not self._eligible(self.skills[sid], schema) or not self._compatible(selected + [sid]):
                    continue
                values = self._skill_features(sid, selected, plan, schema, relevance)
                if values["coverage"] <= 0 and values["check"] <= 0 and values["connectivity"] <= 0:
                    continue
                score, features = weighted("skill", values)
                if score < self.config["skill_min"]:
                    continue
                if self._fits(plan, selected + [sid], schema):
                    options.append((score, sid, features))
                else:
                    trace["budget_rejections"].append({"stage": "bottleneck", "id": sid})
            if not options:
                break
            score, sid, features = min(options, key=lambda row: (-row[0], seed_rank.get(row[1], 10**9), row[1]))
            selected.append(sid)
            trace["skill_steps"].append({"id": sid, "stage": "bottleneck", "score": score, "features": features})
        for _ in range(self.config["backfill_cap"]):
            debt = set(self._debt(selected, schema))
            if not debt or len(selected) >= self.config["top_n"]:
                break
            options = []
            for sid in sorted(activated - set(selected)):
                gain = debt & self.visible_facets[sid]
                if (not gain or not self._eligible(self.skills[sid], schema) or
                        not self._compatible(selected + [sid]) or not self._fits(plan, selected + [sid], schema)):
                    continue
                score, features = weighted("skill", self._skill_features(sid, selected, plan, schema, relevance))
                options.append((len(gain), score, sid, sorted(gain), features))
            if not options:
                break
            _, score, sid, gain, features = min(options, key=lambda row: (-row[0], -row[1], seed_rank.get(row[2], 10**9), row[2]))
            selected.append(sid)
            trace["backfill_steps"].append({"id": sid, "covered_debt": gain, "score": score, "features": features})
        # Promote a specific presented lead if it was previously only support.
        specific_presented = [gid for gid in plan if self.groups[gid]["lead"] in selected and
                              set(self.skills[self.groups[gid]["lead"]]["anchors"]) & set(schema["high_confidence"])]
        if specific_presented and plan[0] not in specific_presented:
            promoted = specific_presented[0]
            plan = [promoted] + [gid for gid in plan if gid != promoted]
            trace["anchor"]["promoted_after_bottleneck"] = promoted
        retained = [gid for gid in plan if set(self.groups[gid]["members"]) & set(selected)]
        trace["pruned_groups"] = [gid for gid in plan if gid not in retained]
        plan = retained
        self._prepare_payloads(text, selected, schema)
        rendered = self._render(plan, selected, schema)
        if len(rendered) > self.config["max_context_chars"]:
            raise RuntimeError("Final contract exceeds verified budget; refusing unlogged truncation")
        payloads = [self.payloads[sid] for sid in selected]
        bundle = {"schema_version": 1, "kind": "goskills_bundle", "method": "goskills-paper-complete-groups-v3",
                  "optimization_stage": "typed-support-seeded-dependency-prefix-safe-coherent-presentation",
                  "query": query, "public_context_sha256": canonical_hash(public_context), "schema": schema,
                  "config": self.config, "seed_evidence": evidence, "plan": plan,
                  "plan_details": [{key:self.groups[gid][key] for key in ("id", "lead", "members", "roles")} for gid in plan],
                  "anchor_skill_id": next((self.groups[gid]["lead"] for gid in plan if self.groups[gid]["lead"] in selected), None),
                  "presented_roles": self._roles(plan, selected),
                  "presented_skills": payloads, "coverage_debt": self._debt(selected, schema),
                  "rendered_context": rendered, "rendered_chars": len(rendered),
                  "trace": trace, "activated_skill_ids": sorted(activated),
                  "pool_hash": canonical_hash(self.pool), "provenance": self.pool.get("provenance", {}),
                  "budget": {"max_skills": self.config["top_n"], "max_skill_body_chars": self.config["max_skill_chars"],
                             "max_context_chars": self.config["max_context_chars"], "backfill_cap": self.config["backfill_cap"]}}
        return copy.deepcopy(bundle)
