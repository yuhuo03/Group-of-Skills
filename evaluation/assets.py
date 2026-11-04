"""Read-only checks binding a retrieval pool to the actual host skill library.

The host library is checked independently of the paths shown to a container.
No source text, provider, simulator, or secret is emitted by these checks.
"""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import hashlib
from goskills.io import read_json, validate_pool


@contextmanager
def pool_view(path):
    path = Path(path)
    if path.is_file():
        yield validate_pool(read_json(path))
        return
    from goskills_eval.compiled_pool import retriever
    reader = retriever(path, '/source-identity-only')
    try:
        yield reader.pool
    finally:
        for key in ('skills', 'groups', 'facet_index', 'member_index', 'adjacency'):
            mapping = reader.pool[key]
            if hasattr(mapping.__getitem__, 'cache_clear'):
                mapping.__getitem__.cache_clear()
            mapping.db.close()


def validate_sources(skills, skills_root):
    """Require exact membership and source bytes; never trust path names alone."""
    root = Path(skills_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Skill library must be a directory')
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Skill library must not contain symlinks')
        if path.name == 'SKILL.md' and path.is_file():
            files[path.relative_to(root).as_posix()] = path
    expected = set()
    records = []
    for skill in skills:
        relative = skill.get('source_path')
        if not isinstance(relative, str):
            raise ValueError('Pool source path is missing')
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or '\\' in relative or relative != path.as_posix():
            raise ValueError('Pool source path is not library-relative')
        if relative in expected or relative not in files:
            raise ValueError('Pool/library source membership mismatch: '+relative)
        expected.add(relative)
        raw = files[relative].read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        recorded = skill.get('metadata', {}).get('source_sha256')
        if recorded is not None:
            if recorded != digest:
                raise ValueError('Pool/library source hash mismatch: '+relative)
        else:
            # Non-native authored graphs can retain full source text instead
            # of a native export hash. Body alone can be a parsed fragment.
            text = skill.get('text')
            if not isinstance(text, str) or raw.decode('utf-8') != text:
                raise ValueError('Pool/library full source text mismatch: '+relative)
        records.append((relative, digest))
    if expected != set(files):
        raise ValueError('Library contains skills absent from the pool')
    if not expected:
        raise ValueError('Empty skill library')
    import json
    identity = hashlib.sha256(json.dumps(sorted(records), separators=(',', ':')).encode()).hexdigest()
    return {'status': 'PASSED', 'source_documents': len(expected), 'source_manifest_sha256': identity}


def validate_library(pool, skills_root):
    """Check JSON and compiled pool sources against the mounted host library."""
    with pool_view(pool) as view:
        result = validate_sources((view['skills'][sid] for sid in view['skills']), skills_root)
        expected = view.get('provenance', {}).get('source_provenance', {}).get('library_hash')
        if expected is not None:
            from goskills.native import _tree_hash
            if _tree_hash(Path(skills_root).resolve()) != expected:
                raise ValueError('Native pool/library auxiliary-file hash mismatch')
        return result
