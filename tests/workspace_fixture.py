"""Synthetic identity inputs, never an actual GoS index or provider result."""
import hashlib
import json
import struct
from pathlib import Path
from goskills.native import _tree_hash, OFFICIAL_COMMIT
from goskills_eval.workspace import bind_workspace


def make_workspace(workspace, library):
    workspace, library = Path(workspace), Path(library)
    workspace.mkdir(exist_ok=True)
    skills = []
    for path in sorted(library.rglob('SKILL.md')):
        relative = path.relative_to(library).as_posix()
        text = path.read_text()
        skills.append({'id': relative, 'name': path.parent.name, 'body': text,
                       'text': text, 'source_path': relative,
                       'metadata': {'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}})
    count = len(skills)
    # Only a synthetic HNSW header; native loading/embedding is always stubbed.
    size, label, offset = 6160, 6152, 8
    (workspace/'entities_hnsw_index_1536.bin').write_bytes(
        struct.pack('<6Q', 0, count, count, size, label, offset) + bytes(count*size))
    (workspace/'graph_igraph_data.pklz').write_bytes(b'synthetic graph, not a pickle')
    (workspace/'construction_report.json').write_text('{}')
    graph = {'schema_version': 1, 'kind': 'goskills_graph', 'skills': skills, 'edges': [],
             'provenance': {'official_commit': OFFICIAL_COMMIT, 'provider_calls_performed': 0,
                            'provider_failures': 0, 'source_workspace_unchanged': True,
                            'model': 'text-embedding-3-small', 'dim': 1536,
                            'actual_vector_shape': [count, 1536], 'source_document_count': count,
                            'workspace_hash': _tree_hash(workspace), 'library_hash': _tree_hash(library)}}
    export = workspace.with_name(workspace.name+'.graph.json')
    export.write_text(json.dumps(graph))
    bind_workspace(export,workspace,library)
    return graph
