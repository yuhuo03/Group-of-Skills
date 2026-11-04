"""Five real skill methods, with isolated native workspaces and checked embeddings.

No dependency import or provider request occurs at module import. GoSkills D is
lexical; Vector/Graph call their distinct pinned upstream algorithms and cannot
silently substitute D or a zero-vector fallback when embeddings fail.
"""
from pathlib import Path
import asyncio
import contextlib
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys

from .common import write

METHODS = ('noskills', 'vanilla', 'vector', 'native-gos', 'goskills-d')
OFFICIAL_COMMIT = '203f60a2c689da055ce1ac351eb3cb9912a3bca7'


def validate_output(directory, **inputs):
    """Refuse outputs inside input assets or containing them, before any writes."""
    target = Path(directory).expanduser().resolve()
    for name, value in inputs.items():
        if value is None:
            continue
        source = Path(value).expanduser().resolve()
        if target == source or source in target.parents or target in source.parents:
            raise ValueError(f'Output must be separate from input {name}')


def validate_resources(method, *, skills_root=None, pool=None, workspace=None, upstream=None, check_files=False):
    if method not in METHODS:
        raise ValueError('Unknown method: ' + str(method))
    required = []
    if method != 'noskills':
        required.append(('skills_root', skills_root, 'dir'))
    if method == 'goskills-d':
        required.append(('pool', pool, 'any'))
    if method in {'vanilla', 'vector', 'native-gos'}:
        required.append(('upstream', upstream, 'dir'))
    if method in {'vector', 'native-gos'}:
        required.append(('workspace', workspace, 'dir'))
    for name, value, kind in required:
        if not value:
            raise ValueError(f'{name} is required for {method}')
        if check_files:
            path = Path(value)
            if not path.exists() or kind == 'dir' and not path.is_dir():
                raise ValueError(f'{name} is missing or has the wrong type')
            if name == 'skills_root' and not any(path.rglob('SKILL.md')):
                raise ValueError('skills_root contains no SKILL.md library')


def prepare_upstream(upstream):
    """Select the historical checkout before importing its singleton settings."""
    root = Path(upstream).expanduser().resolve()
    try:
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.run(['git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except (OSError, subprocess.CalledProcessError):
        raise ValueError('upstream must be the pinned Graph of Skills git checkout') from None
    if commit != OFFICIAL_COMMIT or dirty:
        raise ValueError('upstream commit or tracked source differs from the recorded GoS version')
    for name in ('gos', 'evaluation.skill', 'evaluation.alfworld_run'):
        module = sys.modules.get(name)
        if module is not None and getattr(module, '__file__', None):
            if not Path(module.__file__).resolve().is_relative_to(root):
                raise RuntimeError('Different upstream module already loaded; use a fresh worker')
    os.environ['GOS_EMBEDDING_MODEL'] = 'openai/text-embedding-3-small'
    os.environ['GOS_EMBEDDING_DIM'] = '1536'
    os.environ['GOS_ENABLE_QUERY_REWRITE'] = 'false'
    # The pinned evaluation.utils eagerly constructs an unused legacy client
    # even for all_full. Alias the documented credentials; do not make a call.
    if os.environ.get('OPENAI_API_KEY'):
        os.environ['API_KEY'] = os.environ['OPENAI_API_KEY']
    os.environ['BASE_URL'] = os.environ.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1'
    sys.path.insert(0, str(root))
    return root


def _load_official(upstream):
    prepare_upstream(upstream)
    gos = importlib.import_module('gos')
    engine = importlib.import_module('gos.core.engine')
    settings = engine.settings
    if settings.EMBEDDING_MODEL != 'openai/text-embedding-3-small' or settings.EMBEDDING_DIM != 1536:
        raise RuntimeError('GoS settings were loaded with an incompatible embedding model/dimension')
    return gos.SkillGraphRAG, engine.build_default_embedding_service


class CheckedEmbeddings:
    """Guard the original GoS embedding provider; persist metadata, not credentials."""
    def __init__(self, directory, factory):
        self.directory = Path(directory)
        self.embedding_dim = 1536
        self.calls = 0
        self.failed = False
        self.real = factory()

    async def encode(self, texts, model=None):
        import numpy as np
        self.calls += 1
        event = {'texts_sha256': hashlib.sha256(json.dumps(texts).encode()).hexdigest(),
                 'model': 'text-embedding-3-small', 'dimensions': 1536, 'offline_fixture': False}
        try:
            out = await self.real.encode(texts)
            if out.shape != (len(texts), 1536) or not np.isfinite(out).all():
                raise ValueError('embedding dimension or finite-value check failed')
            event['status'] = 'PASSED'
            return out
        except Exception as exc:
            self.failed = True
            event.update(status='FAILED', error_type=type(exc).__name__)
            raise RuntimeError('embedding_transport_failed') from None
        finally:
            write(self.directory/'embedding'/f'{self.calls:04d}.json', event, True)


class OfficialRetriever:
    """Pinned Graph/Vector engine, sharing the historical ALFWorld interface."""
    def __init__(self, directory, workspace, upstream):
        self.directory = Path(directory)
        source = Path(workspace).expanduser().resolve()
        validate_output(directory, workspace=source, upstream=upstream)
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory/'index'
        if target.exists():
            raise FileExistsError('Use a fresh retrieval worker directory')
        if not source.is_dir():
            raise ValueError('workspace must be an existing GoS index directory')
        for path in source.rglob('*'):
            if path.is_symlink():
                raise ValueError('Workspace symlinks are not accepted')
        engine, factory = _load_official(upstream)
        # The official loader may update storage. Only a per-worker copy is used.
        shutil.copytree(source, target)
        self.embed = CheckedEmbeddings(self.directory, factory)
        self.real = engine(working_dir=str(target), config=engine.Config(
            working_dir=str(target), prebuilt_working_dir=str(target), llm_service=None,
            embedding_service=self.embed, enable_query_rewrite=False,
            seed_top_k=5, retrieval_top_n=4, max_skill_chars=1800, max_context_chars=9000))
        self.n = 0

    async def call(self, name, text, **kwargs):
        self.n += 1
        before = self.embed.calls
        result = await getattr(self.real, name)(text, **kwargs)
        if self.embed.failed or self.embed.calls <= before:
            raise RuntimeError('embedding_fallback_forbidden')
        if len(result.skills) > kwargs.get('top_n', 4):
            raise ValueError('retrieval skill budget exceeded')
        write(self.directory/'retrievals'/f'{self.n:04d}.json', {
            'method': name, 'query': text, 'top_n': kwargs.get('top_n', 4),
            'skills': [{'name': s.name, 'payload': s.payload} for s in result.skills],
            'summary': result.summary, 'embedding_calls': self.embed.calls-before,
            'status': 'PASSED'}, True)
        return result

    async def async_retrieve(self, text, **kwargs):
        return await self.call('async_retrieve', text, **kwargs)

    async def async_retrieve_vector(self, text, **kwargs):
        return await self.call('async_retrieve_vector', text, **kwargs)


def query(method, text, directory, *, skills_root=None, pool=None, workspace=None, upstream=None,
          source_root='/opt/graphskills/skills'):
    """Return the method's real context; directory may already exist, records may not."""
    validate_resources(method, skills_root=skills_root, pool=pool, workspace=workspace,
                       upstream=upstream, check_files=True)
    validate_output(directory, skills_root=skills_root, pool=pool, workspace=workspace, upstream=upstream)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    embed_count = 0
    if method == 'noskills':
        content = ''
    elif method == 'vanilla':
        prepare_upstream(upstream)
        SkillModule = importlib.import_module('evaluation.skill').SkillModule
        sm = SkillModule(skills_dir=str(Path(skills_root).resolve()), model='gpt-5.4',
                         mode='all_full', enable_alfworld_gating=False)
        content = sm.get_all_full_exposure_message().replace(str(Path(skills_root).resolve()), source_root)
        if not content:
            raise ValueError('Empty skill catalog; check the SKILL.md library format')
    elif method == 'goskills-d':
        from .retrieval import DContext
        bundle = DContext(pool, source_root).query(text)
        content = bundle['rendered_context']
        write(directory/'bundle.json', bundle, True)
    else:
        retriever = OfficialRetriever(directory, workspace, upstream)
        async def get():
            options = {'top_n': 4, 'max_chars_per_skill': 1800, 'max_context_chars': 9000}
            if method == 'native-gos':
                return await retriever.async_retrieve(text, seed_top_k=5, **options)
            return await retriever.async_retrieve_vector(text, **options)
        result = asyncio.run(get())
        rewrite = importlib.import_module('gos.interfaces.cli')._rewrite_source_paths
        content = rewrite(result.rendered_context, source_root)
        embed_count = retriever.embed.calls
        write(directory/'bundle.json', result.model_dump(), True)
    if method not in {'vanilla', 'noskills'} and len(content) > 9000:
        raise ValueError('context_budget_exceeded')
    write(directory/'backend_receipt.json', {
        'status': 'PASSED', 'method': method, 'embedding_calls': embed_count,
        'query_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
        'catalog_semantics': 'full_metadata' if method == 'vanilla' else None}, True)
    return content


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--method', choices=METHODS, required=True)
    parser.add_argument('--query', required=True)
    parser.add_argument('--directory', type=Path, required=True)
    for name in ('skills-root', 'pool', 'workspace', 'upstream'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--source-root', default='/opt/graphskills/skills')
    parser.add_argument('--execute', action='store_true', help='Allow the embedding request for vector/native-gos; those methods otherwise print a plan')
    args = parser.parse_args()
    validate_resources(args.method, skills_root=args.skills_root, pool=args.pool, workspace=args.workspace, upstream=args.upstream)
    validate_output(args.directory, skills_root=args.skills_root, pool=args.pool, workspace=args.workspace, upstream=args.upstream)
    if args.method in {'vector', 'native-gos'} and not args.execute:
        print(json.dumps({'status': 'PLAN_ONLY', 'method': args.method, 'directory': str(args.directory), 'embedding_model': 'text-embedding-3-small', 'embedding_dimensions': 1536}))
        return
    args.directory.mkdir(parents=True, exist_ok=False)
    try:
        with (args.directory/'upstream.log').open('x') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            content = query(args.method, args.query, args.directory, skills_root=args.skills_root,
                            pool=args.pool, workspace=args.workspace, upstream=args.upstream,
                            source_root=args.source_root)
        print(content)
    except Exception as exc:
        write(args.directory/'failure.json', {'status': 'FAILED', 'error_type': type(exc).__name__}, True)
        raise SystemExit('Retrieval failed; inspect the private output directory.') from None

if __name__ == '__main__':
    main()
