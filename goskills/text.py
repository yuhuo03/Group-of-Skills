from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any


TOKEN_STOPWORDS = {
    "able",
    "about",
    "after",
    "again",
    "against",
    "all",
    "also",
    "and",
    "any",
    "are",
    "artifact",
    "artifacts",
    "based",
    "before",
    "being",
    "between",
    "both",
    "but",
    "can",
    "cannot",
    "code",
    "current",
    "data",
    "define",
    "defined",
    "directly",
    "does",
    "done",
    "each",
    "engineer",
    "every",
    "file",
    "files",
    "final",
    "for",
    "from",
    "given",
    "has",
    "have",
    "here",
    "how",
    "include",
    "includes",
    "including",
    "input",
    "into",
    "its",
    "just",
    "list",
    "local",
    "make",
    "many",
    "more",
    "most",
    "must",
    "need",
    "object",
    "only",
    "other",
    "output",
    "path",
    "paths",
    "please",
    "query",
    "read",
    "record",
    "required",
    "result",
    "same",
    "set",
    "should",
    "since",
    "skill",
    "skills",
    "some",
    "specified",
    "string",
    "such",
    "task",
    "tasks",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "use",
    "used",
    "using",
    "value",
    "very",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "within",
    "without",
    "you",
    "your",
}

OPERATION_HINTS = {
    "analyze",
    "audit",
    "build",
    "check",
    "classify",
    "compute",
    "convert",
    "debug",
    "detect",
    "diagnose",
    "edit",
    "evaluate",
    "extract",
    "fix",
    "generate",
    "implement",
    "match",
    "migrate",
    "normalize",
    "optimize",
    "parse",
    "patch",
    "profile",
    "reconcile",
    "recover",
    "refactor",
    "render",
    "repair",
    "test",
    "transform",
    "validate",
    "verify",
    "write",
}

CONSTRAINT_HINTS = {
    "backward",
    "compatible",
    "deterministic",
    "exact",
    "fast",
    "minimal",
    "portable",
    "preserve",
    "reliable",
    "robust",
    "safe",
    "scalable",
    "secure",
    "stable",
}

FAILURE_HINTS = {
    "bug",
    "crash",
    "error",
    "failure",
    "fail",
    "flaky",
    "invalid",
    "latency",
    "leak",
    "missing",
    "mismatch",
    "regression",
    "slow",
    "timeout",
}

VERIFIER_HINTS = {
    "audit",
    "check",
    "checker",
    "diff",
    "expected",
    "inspect",
    "regression",
    "review",
    "schema",
    "test",
    "tests",
    "validate",
    "validation",
    "verify",
    "verifier",
}

FILE_FORMAT_TOKENS = {
    "bib",
    "csv",
    "docx",
    "gif",
    "html",
    "jpeg",
    "jpg",
    "json",
    "jsonl",
    "md",
    "mp3",
    "mp4",
    "pdf",
    "png",
    "pptx",
    "stl",
    "svg",
    "toml",
    "tsv",
    "txt",
    "wav",
    "xls",
    "xlsx",
    "xml",
    "yaml",
    "yml",
}

TECH_TOKENS = {
    "bash",
    "browser",
    "c",
    "cpp",
    "css",
    "d3",
    "docker",
    "excel",
    "flink",
    "go",
    "html",
    "java",
    "javascript",
    "lean",
    "lean4",
    "maven",
    "node",
    "pdf",
    "python",
    "react",
    "rust",
    "spark",
    "sql",
    "suricata",
    "threejs",
    "typescript",
    "xlsx",
}

TECH_CONFLICT_FAMILIES = [
    {"python", "java", "javascript", "typescript", "go", "rust", "cpp", "c"},
    {"react", "d3", "threejs"},
    {"xlsx", "csv", "json", "pdf", "docx", "pptx", "html", "xml"},
]


def split_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def maybe_singularize(token: str) -> str:
    if len(token) <= 4 or not token.endswith("s"):
        return token
    if token.endswith(("ss", "us", "is")):
        return token
    return token[:-1]


def signature_tokens(values: Iterable[Any]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = str(value or "").lower()
        for phrase in re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)+", text):
            compact = re.sub(r"[^a-z0-9]+", "_", phrase).strip("_")
            if 3 <= len(compact) <= 48 and compact not in TOKEN_STOPWORDS:
                tokens.add(compact)
                collapsed = compact.replace("_", "")
                if 3 <= len(collapsed) <= 32 and collapsed not in TOKEN_STOPWORDS:
                    tokens.add(collapsed)
        for token in re.findall(r"[a-z0-9]+", text):
            if len(token) < 2 or token in TOKEN_STOPWORDS:
                continue
            tokens.add(token)
            singular = maybe_singularize(token)
            if singular != token and singular not in TOKEN_STOPWORDS:
                tokens.add(singular)
    return tokens


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def slugify(value: str, *, fallback: str = "group") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def token_jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right))


def build_idf_weights(token_map: dict[str, set[str]], query_tokens: set[str] | None = None) -> dict[str, float]:
    vocabulary = set(query_tokens or set())
    if not vocabulary:
        vocabulary = {token for tokens in token_map.values() for token in tokens}
    if not vocabulary:
        return {}
    document_count = max(len(token_map), 1)
    raw: dict[str, float] = {}
    for token in vocabulary:
        frequency = sum(1 for tokens in token_map.values() if token in tokens)
        raw[token] = math.log(1.0 + ((document_count + 1.0) / (frequency + 1.0)))
    total = sum(raw.values())
    if total <= 0.0:
        uniform = 1.0 / float(len(raw))
        return {token: uniform for token in raw}
    return {token: weight / total for token, weight in raw.items()}


def weighted_overlap(tokens: set[str], weights: dict[str, float]) -> float:
    return sum(weight for token, weight in weights.items() if token in tokens)


def weighted_gain(tokens: set[str], weights: dict[str, float], covered: set[str]) -> float:
    return sum(weight for token, weight in weights.items() if token in tokens and token not in covered)


def extract_query_focus_text(query: str, *, max_chars: int = 1200) -> str:
    lowered = query.lower()
    for marker in ("your task is", "task is", "objective:", "goal:", "problem:"):
        position = lowered.find(marker)
        if position >= 0:
            return query[position : position + max_chars]
    return query[:max_chars]


def decompose_query(query: str, vocabulary: set[str] | None = None) -> dict[str, list[str]]:
    tokens = signature_tokens([extract_query_focus_text(query)])
    vocabulary = vocabulary or set()
    operations = sorted(tokens & OPERATION_HINTS)
    constraints = sorted(tokens & CONSTRAINT_HINTS)
    failures = sorted(tokens & FAILURE_HINTS)
    artifacts = sorted(tokens & FILE_FORMAT_TOKENS)
    technologies = sorted(tokens & TECH_TOKENS)
    reserved = set(operations) | set(constraints) | set(failures) | set(artifacts)

    domain_candidates = [
        token
        for token in tokens
        if token not in reserved and (not vocabulary or token in vocabulary or token in TECH_TOKENS)
    ]
    domain_candidates.sort(key=lambda token: (token in technologies, "_" in token, len(token)), reverse=True)
    domains = unique_preserving_order(technologies + domain_candidates)[:5]

    core = unique_preserving_order(
        domains
        + operations
        + failures
        + constraints
        + artifacts
        + sorted(tokens - reserved, key=lambda item: (item in vocabulary, len(item)), reverse=True)
    )[:8]
    return {
        "tokens": sorted(tokens),
        "core_facets": core,
        "domains": domains,
        "operations": operations[:5],
        "artifacts": artifacts[:5],
        "failure_modes": failures[:5],
        "constraints": constraints[:5],
    }


def query_focus_tokens(decomposition: dict[str, list[str]]) -> set[str]:
    ordered = unique_preserving_order(
        decomposition.get("core_facets", [])
        + decomposition.get("artifacts", [])
        + decomposition.get("operations", [])
        + decomposition.get("failure_modes", [])
        + decomposition.get("constraints", [])
        + decomposition.get("domains", [])
    )
    return set(ordered or decomposition.get("tokens", []))


def technology_family_conflict(left_tokens: set[str], right_tokens: set[str]) -> bool:
    for family in TECH_CONFLICT_FAMILIES:
        left = left_tokens & family
        right = right_tokens & family
        if left and right and left.isdisjoint(right):
            return True
    return False
