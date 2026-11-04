"""Bind trusted native exports to movable workspace/library inputs, offline.

The binding lives beside the workspace, so it never changes the exported index
hash. This checks consistency of trusted artifacts, not third-party authenticity.
No pickle loader, provider client or upstream engine is imported here.
"""
from pathlib import Path
import argparse
import json
import re
from goskills.config import canonical_hash
from goskills.io import read_json, validate_graph, write_json
from goskills.native import _file_hash, _tree_hash, _index_header, OFFICIAL_COMMIT
from goskills_eval.assets import validate_sources, pool_view


def identity_path(workspace):
    workspace = Path(workspace).resolve()
    return workspace.with_name(workspace.name + '.identity.json')


def _directory(path):
    path = Path(path).resolve(strict=True)
    if not path.is_dir() or any(p.is_symlink() for p in path.rglob('*')):
        raise ValueError('Workspace/library must be a directory without symlinks')
    return path


def bind_workspace(graph_path, workspace, skills_root):
    """Save a compact binding only after matching the export's full source hashes."""
    graph_path = Path(graph_path).resolve(strict=True)
    workspace, skills_root = _directory(workspace), _directory(skills_root)
    target = identity_path(workspace)
    from goskills_eval.skill import validate_output
    validate_output(target, graph=graph_path, workspace=workspace, skills_root=skills_root)
    if target.exists():
        raise FileExistsError('Workspace identity already exists; do not overwrite it')
    export_hash = _file_hash(graph_path)
    graph = validate_graph(read_json(graph_path))
    provenance = graph.get('provenance', {})
    if (provenance.get('official_commit') != OFFICIAL_COMMIT or
            provenance.get('provider_calls_performed') != 0 or
            provenance.get('provider_failures') != 0 or
            provenance.get('source_workspace_unchanged') is not True):
        raise ValueError('Use the verified export-native output for this workspace')
    model = str(provenance.get('model', '')).removeprefix('openai/')
    if model != 'text-embedding-3-small' or provenance.get('dim') != 1536:
        raise ValueError('Evaluation requires text-embedding-3-small/1536')
    sources = validate_sources(graph['skills'], skills_root)
    header = _index_header(workspace)
    shape = [sources['source_documents'], 1536]
    if (provenance.get('actual_vector_shape') != shape or
            provenance.get('source_document_count') != shape[0] or
            [header['count'], header['dim']] != shape):
        raise ValueError('Native export, index and library dimensions/counts differ')
    hashes = {'workspace_hash': _tree_hash(workspace), 'library_hash': _tree_hash(skills_root)}
    if any(provenance.get(k) != v for k, v in hashes.items()):
        raise ValueError('Workspace/library changed since native export')
    # All graph/vector bytes are bound by workspace_hash, not just index count.
    receipt = {'schema_version': 1, 'kind': 'goskills_workspace_identity',
               'official_commit': OFFICIAL_COMMIT, 'embedding_model': model,
               'embedding_dim': 1536, 'source_document_count': shape[0],
               'source_manifest_sha256': sources['source_manifest_sha256'],
               'source_graph_hash': canonical_hash(graph),
               'native_export_sha256': export_hash, **hashes}
    if _file_hash(graph_path) != export_hash:
        raise ValueError('Native export changed during binding')
    write_json(target, receipt)
    return receipt


def validate_workspace(workspace, skills_root, *, pool=None):
    workspace, skills_root = _directory(workspace), _directory(skills_root)
    path = identity_path(workspace)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Missing workspace identity; run python -m goskills_eval.workspace bind after export-native')
    receipt = read_json(path)
    if (receipt.get('schema_version') != 1 or receipt.get('kind') != 'goskills_workspace_identity' or
            receipt.get('official_commit') != OFFICIAL_COMMIT or
            receipt.get('embedding_model') != 'text-embedding-3-small' or
            receipt.get('embedding_dim') != 1536):
        raise ValueError('Invalid or incompatible workspace identity')
    for key in ('source_manifest_sha256', 'source_graph_hash', 'native_export_sha256',
                'workspace_hash', 'library_hash'):
        if not isinstance(receipt.get(key), str) or not re.fullmatch('[0-9a-f]{64}', receipt[key]):
            raise ValueError('Missing workspace identity hash: ' + key)
    if (_tree_hash(workspace) != receipt['workspace_hash'] or
            _tree_hash(skills_root) != receipt['library_hash']):
        raise ValueError('Workspace/library identity mismatch')
    header = _index_header(workspace)
    if [header['count'], header['dim']] != [receipt['source_document_count'], 1536]:
        raise ValueError('Workspace index dimension/count mismatch')
    if pool is not None:
        with pool_view(pool) as view:
            if view['provenance'].get('source_graph_hash') != receipt['source_graph_hash']:
                raise ValueError('GoSkills pool and graph/vector workspace came from different graph exports')
    return receipt


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['bind', 'check'])
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--skills-root', type=Path, required=True)
    p.add_argument('--graph', type=Path, help='Verified export-native JSON; required for bind')
    a = p.parse_args(argv)
    if a.action == 'bind':
        if a.graph is None:
            p.error('bind requires --graph')
        receipt = bind_workspace(a.graph, a.workspace, a.skills_root)
    else:
        if a.graph is not None:
            p.error('--graph is used only by bind')
        receipt = validate_workspace(a.workspace, a.skills_root)
    print(json.dumps({'status': 'PASSED', 'identity': str(identity_path(a.workspace)),
                      'source_documents': receipt['source_document_count'], 'provider_calls': 0}))


if __name__ == '__main__':
    main()
