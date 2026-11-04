"""Build fresh, source-bound component pools for new controlled experiments."""
import argparse
import json
from pathlib import Path

from goskills.config import canonical_hash
from goskills.io import read_json, write_json
from goskills_eval.assets import validate_sources
from goskills_eval.experiments.ablation_conditions import CONDITIONS, DESCRIPTIONS, build_condition
from goskills_eval.experiments.bindings import fingerprint


def prepare(graph_path, skills_root, output, conditions, *, execute=False):
    graph_path, skills_root, output = Path(graph_path).resolve(strict=True), Path(skills_root).resolve(strict=True), Path(output).absolute()
    if output.exists() or output.resolve() != output:
        raise ValueError('Use a new output directory without symlinks')
    if output.is_relative_to(skills_root) or skills_root.is_relative_to(output) or graph_path.is_relative_to(output):
        raise ValueError('Output overlaps input assets')
    if not conditions or len(set(conditions)) != len(conditions) or any(c not in CONDITIONS for c in conditions):
        raise ValueError('Select unique known component conditions')
    graph = read_json(graph_path)
    validate_sources(graph['skills'], skills_root)
    inputs = {str(graph_path): fingerprint(graph_path), str(skills_root): fingerprint(skills_root)}
    report = {'schema_version': 1, 'kind': 'goskills_component_pools', 'inputs': inputs,
              'historical_paper_replication': False, 'provider_calls': 0,
              'conditions': {name: DESCRIPTIONS[name] for name in conditions}}
    if not execute:
        return report
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/'PLAN.json', report)
    hashes = {}
    for condition in conditions:
        pool = build_condition(graph, condition)
        write_json(output/(condition+'.json'), pool)
        hashes[condition] = canonical_hash(pool)
    if any(fingerprint(path) != value for path, value in inputs.items()):
        raise ValueError('Inputs changed during component preparation')
    write_json(output/'COMPLETE.json', {'status': 'PREPARED', 'pools': hashes, 'provider_calls': 0})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--skills-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--conditions', default=','.join(CONDITIONS))
    parser.add_argument('--execute', action='store_true', help='Build local pools; no agent or model requests')
    args = parser.parse_args()
    print(json.dumps(prepare(args.graph, args.skills_root, args.output,
                             args.conditions.split(','), execute=args.execute), indent=2))


if __name__ == '__main__':
    main()
