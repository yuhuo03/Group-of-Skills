"""Prepare nested skill libraries without querying providers or task oracles."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from goskills.io import read_json, write_json
from goskills_eval.experiments.bindings import fingerprint


def library_members(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Expected a regular skill-library directory')
    members = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Skill libraries must not contain symlinks')
        if path.name == 'SKILL.md' and path.is_file():
            relative = path.relative_to(root)
            if len(relative.parts) != 2:
                raise ValueError('Scale libraries require one top-level directory per skill')
            members[relative.parts[0]] = path.parent
    if not members:
        raise ValueError('Empty skill library')
    return members


def member_files(directory):
    files = {}
    for path in sorted(Path(directory).rglob('*')):
        if path.is_symlink():
            raise ValueError('Skill sources must not contain symlinks')
        if path.name == '.env' or path.name.startswith('.env.') and path.name != '.env.example':
            raise ValueError('Remove private environment files from the source library first')
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise ValueError('Unsupported skill source file type')
    return files


def prepare(source, output, sizes, required=(), *, execute=False):
    source, output = Path(source).absolute(), Path(output).absolute()
    if source.resolve() != source or output.resolve() != output:
        raise ValueError('Use paths without symlink components')
    if output.exists():
        raise FileExistsError('Use a new skillset output directory')
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Skillset output overlaps source library')
    members = library_members(source)
    if (not sizes or any(type(n) is not int or n < 1 for n in sizes)
            or len(set(sizes)) != len(sizes) or max(sizes) > len(members)):
        raise ValueError('Sizes must be unique positive integers within the source library')
    if (not isinstance(required, (list, tuple)) or any(not isinstance(x, str) for x in required)
            or len(set(required)) != len(required) or not set(required) <= members.keys()):
        raise ValueError('Required members must be unique source-library directory names')
    if min(sizes) < len(required):
        raise ValueError('Requested size is smaller than required membership')
    order = sorted(required) + sorted(set(members) - set(required))
    selected = {name: member_files(members[name]) for name in order[:max(sizes)]}
    attribution = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in source.iterdir() if p.is_file()
                   and p.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE'))}
    plan = {'schema_version': 1, 'kind': 'goskills_skillsets',
            'protocol': 'required-members-then-lexicographic-nested-v1',
            'source': str(source), 'source_binding': fingerprint(source),
            'required_members': sorted(required), 'attribution': attribution,
            'cohort': 'new-experiment-inputs; historical membership is not asserted',
            'libraries': [{'size': n, 'directory': f'skills_{n}',
                           'members': {name: selected[name] for name in order[:n]}}
                          for n in sorted(sizes)]}
    if not execute:
        return plan
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/'PLAN.json', plan)
    for row in plan['libraries']:
        target = output/row['directory']
        target.mkdir()
        for name, expected in row['members'].items():
            shutil.copytree(members[name], target/name, symlinks=True)
            if member_files(target/name) != expected:
                raise ValueError('Copied skill changed during preparation')
        for name, expected in attribution.items():
            shutil.copyfile(source/name, target/name)
            if hashlib.sha256((target/name).read_bytes()).hexdigest() != expected:
                raise ValueError('Attribution changed during preparation')
    if fingerprint(source) != plan['source_binding']:
        raise ValueError('Source library changed during preparation')
    write_json(output/'COMPLETE.json', {'status': 'PREPARED',
               'libraries': {row['directory']: fingerprint(output/row['directory'])
                             for row in plan['libraries']}, 'provider_calls': 0})
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sizes', default='200,500,1000,2000')
    parser.add_argument('--required-members', type=Path, help='JSON list of required skill-directory names')
    parser.add_argument('--execute', action='store_true', help='Copy only local input files; no model calls')
    args = parser.parse_args()
    plan = prepare(args.skills_root, args.output, [int(n) for n in args.sizes.split(',')],
                   read_json(args.required_members) if args.required_members else [], execute=args.execute)
    print(json.dumps(plan, indent=2))


if __name__ == '__main__':
    main()
