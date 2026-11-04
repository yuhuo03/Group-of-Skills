"""Published constants plus explicitly declared reconstruction choices."""
import hashlib
import json
import math

WEIGHTS = {
    "group": (.28, .22, .18, .12, .10, -.05, -.25, -.04),
    "support": (.12, .28, .06, .16, .16, -.18, -.25, -.04),
    "skill": (.18, .24, .12, .20, .08, -.12, -.30, -.08),
}
FEATURES = ("relevance", "coverage", "anchor", "check", "connectivity",
            "redundancy", "negative", "cost")
DEFAULTS = dict(top_n=4, seed_top_k=4, max_skill_chars=1800, max_context_chars=9000,
                max_group_size=3, max_groups=3, backfill_cap=2, neighbor_limit=2,
                affinity_threshold=.35, lambda_prior=.05, lambda_anchor=.18,
                group_min=.14, support_min=.10, skill_min=.10,
                seed_mode="lexical", policy_version="paper-reconstruction-v1")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_config(overrides=None):
    config = dict(DEFAULTS)
    if overrides:
        if set(overrides) - set(config):
            raise ValueError(f"Unknown configuration keys: {sorted(set(overrides)-set(config))}")
        config.update(overrides)
    limits = {"top_n": 4, "seed_top_k": 32, "max_skill_chars": 1800,
              "max_context_chars": 9000, "max_group_size": 3, "max_groups": 3,
              "backfill_cap": 2, "neighbor_limit": 2}
    for key, maximum in limits.items():
        minimum = 0 if key in {"backfill_cap", "neighbor_limit"} else 1
        if type(config[key]) is not int or not minimum <= config[key] <= maximum:
            raise ValueError(f"{key} must be an integer in [{minimum}, {maximum}]")
    for key in ("affinity_threshold", "lambda_prior", "lambda_anchor", "group_min", "support_min", "skill_min"):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key} must be finite in [0, 1]")
    if config["seed_mode"] not in {"lexical", "external"}:
        raise ValueError("seed_mode must be lexical or external")
    if config["policy_version"] != DEFAULTS["policy_version"]:
        raise ValueError("Unknown policy version")
    return config
