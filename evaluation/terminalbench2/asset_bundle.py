"""Prepare only the hash-bound public verifier inputs for portable distribution."""
import argparse
import json
from pathlib import Path
import shutil

from goskills.io import write_json
from goskills_eval.terminalbench2.dependency_transport import Assets, canonical_path, file_sha


def export_assets(config, output):
    assets = Assets(config)
    assets.validate()
    output = canonical_path(output)
    for path in [assets.config, *assets.roots.values()]:
        if output == path or output in path.parents or path in output.parents:
            raise ValueError('Output must be separate from source assets')
    output.mkdir(parents=True, exist_ok=False)
    for name, root in assets.roots.items():
        for row in assets.files(name):
            destination = output/name/row['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            with (root/row['path']).open('rb') as source, destination.open('xb') as target:
                shutil.copyfileobj(source, target, 1024*1024)
            if file_sha(destination) != row['sha256']:
                raise ValueError('Public asset changed during export')
            destination.chmod(0o644)
    # Published last: an interrupted directory without this config is incomplete.
    config_path = output/'assets.json'
    write_json(config_path, {name: name for name in assets.roots})
    return {'config': str(config_path), **Assets(config_path).validate()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_assets(args.config, args.output)))


if __name__ == '__main__':
    main()
