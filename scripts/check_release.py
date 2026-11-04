#!/usr/bin/env python3
"""Offline release checks; print paths/categories only, never sensitive matches."""
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist'}

def files():
    return [p for p in sorted(ROOT.rglob('*')) if p.is_file()
            and not any(x in SKIP or x.endswith('.egg-info') for x in p.relative_to(ROOT).parts)]

def main():
    findings = []
    checked = 0
    patterns = {
        'private_host_path': re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/|/data/huoyu/|10\.240\.0\.1|llm-test-jump|deepwisdom'),
        'credential_shape': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    }
    for p in files():
        name = p.relative_to(ROOT).as_posix()
        if p.is_symlink():
            findings.append({'file': name, 'category': 'symlink'})
            continue
        if p.name == '.env' or p.suffix in {'.pem', '.key'}:
            findings.append({'file': name, 'category': 'credential_file'})
        if p.suffix in {'.py', '.md', '.json', '.toml', '.csv', '.yml', '.yaml', '.cff', '.txt', '.sh'} or p.name == '.env.example':
            checked += 1
            text = p.read_text(encoding='utf-8')
            if p.suffix == '.py':
                ast.parse(text, filename=name)
            if p.suffix == '.json':
                json.loads(text)
            if p.resolve() != Path(__file__).resolve():
                for category, pattern in patterns.items():
                    if pattern.search(text):
                        findings.append({'file': name, 'category': category})
            if p.suffix == '.md':
                for target in re.findall(r'\]\(([^)]+)\)', text):
                    if '://' in target or target.startswith('#'):
                        continue
                    target = target.split('#')[0]
                    if target and not (p.parent / target).exists():
                        findings.append({'file': name, 'category': 'broken_local_link', 'target': target})
    for row in json.loads((ROOT/'provenance/CORE_SOURCE.json').read_text())['files']:
        h = hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()
        if h != row['release_sha256'] or h != row['source_sha256']:
            findings.append({'file': row['path'], 'category': 'frozen_core_changed'})
    for row in json.loads((ROOT/'provenance/RESULTS_SOURCE.json').read_text())['files']:
        if hashlib.sha256((ROOT/row['file']).read_bytes()).hexdigest() != row['release_sha256']:
            findings.append({'file': row['file'], 'category': 'result_source_changed'})
    for filename, key in [('EVALUATION_SOURCE.json', 'release_path'), ('ENVIRONMENT_SOURCE.json', 'file')]:
        evidence = json.loads((ROOT/'provenance'/filename).read_text())
        rows = evidence if isinstance(evidence, list) else evidence['files']
        for row in rows:
            path = ROOT/row[key]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['release_sha256']:
                findings.append({'file': row[key], 'category': 'adapted_source_changed'})
    manifest = ROOT/'SHA256SUMS'
    if manifest.exists():
        listed = set()
        for line in manifest.read_text().splitlines():
            expected, name = line.split('  ', 1)
            if name in listed or Path(name).is_absolute() or '..' in Path(name).parts:
                findings.append({'file': name, 'category': 'invalid_manifest_path'})
                continue
            listed.add(name)
            path = ROOT/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                findings.append({'file': name, 'category': 'release_hash_mismatch'})
        actual = {p.relative_to(ROOT).as_posix() for p in files() if p != manifest}
        for name in sorted(actual - listed):
            findings.append({'file': name, 'category': 'unlisted_release_file'})
    print(json.dumps({'status': 'PASSED' if not findings else 'FAILED', 'text_files_checked': checked,
                      'findings': findings, 'live_benchmarks_executed': False,
                      'limitation': 'Pattern checks are not a full privacy/license audit.'}, indent=2))
    return bool(findings)
if __name__ == '__main__':
    sys.exit(main())
