"""Explicit component experiments for this implementation, not recovered paper runs."""
from copy import deepcopy
import hashlib
from pathlib import Path

from goskills.config import canonical_hash, validate_config
from goskills.groups import build_pool
from goskills.io import validate_pool

# These definitions deliberately avoid claiming that lambda_anchor=0 removes
# anchor selection: the production retriever also has a specificity preference.
CONDITIONS = {
    'full': {},
    'singleton-groups': {'max_group_size': 1},
    'single-group-plan': {'max_groups': 1},
    'no-coverage-backfill': {'backfill_cap': 0},
    'no-group-graph': {},
}

DESCRIPTIONS = {
    'full': 'Unchanged production group construction and retrieval.',
    'singleton-groups': 'Build singleton groups; retain atomic compatibility and online selection.',
    'single-group-plan': 'Limit the selected group plan to one group; retain its members and coverage backfill.',
    'no-coverage-backfill': 'Disable coverage backfill; retain debt accounting and all earlier selection stages.',
    'no-group-graph': 'Remove lifted group edges and adjacency; retain within-group topology and compatibility.',
}


def build_condition(graph, condition):
    if condition not in CONDITIONS:
        raise ValueError('Unknown GoSkills component condition')
    pool = build_pool(graph, validate_config(CONDITIONS[condition]))
    if condition == 'full':
        return pool
    # Always a fresh artifact, never a mutation of a previously frozen pool.
    original = canonical_hash(pool)
    pool = deepcopy(pool)
    if condition == 'no-group-graph':
        pool['group_edges'] = []
        pool['adjacency'] = {gid: [] for gid in pool['groups']}
    pool.pop('integrity')
    pool['provenance']['experiment'] = {
        'condition': condition, 'definition': DESCRIPTIONS[condition],
        'base_pool_hash': original,
        'definition_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'historical_paper_replication': False,
    }
    pool['integrity'] = {'content_sha256': canonical_hash(pool)}
    return validate_pool(pool)
