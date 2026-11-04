"""Offline tests of real five-way dispatch and embedding-failure handling."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'evaluation'))
from goskills_eval import skill as backend
from goskills_eval.alfworld.adapter import official_skill_class


class Matrix:
    def __init__(self, rows=1, cols=1536, finite=True):
        self.shape = (rows, cols)
        self.finite = finite

FAKE_NUMPY = types.SimpleNamespace(isfinite=lambda value: types.SimpleNamespace(all=lambda: value.finite))


class Provider:
    async def encode(self, texts):
        return Matrix(len(texts))


class Result:
    def __init__(self, label):
        self.skills = [types.SimpleNamespace(name=label, payload='source payload')]
        self.summary = label
        self.rendered_context = label
    def model_dump(self):
        return {'summary': self.summary}


class Engine:
    class Config:
        def __init__(self, **kw):
            self.__dict__.update(kw)
    def __init__(self, working_dir, config):
        self.config = config
        self.calls = []
    async def async_retrieve(self, text, **kw):
        self.calls.append(('graph', kw))
        await self.config.embedding_service.encode([text])
        return Result('graph')
    async def async_retrieve_vector(self, text, **kw):
        self.calls.append(('vector', kw))
        await self.config.embedding_service.encode([text])
        return Result('vector')


class BackendTests(unittest.TestCase):
    def test_resource_requirements_cover_all_five_without_provider_imports(self):
        backend.validate_resources('noskills')
        backend.validate_resources('vanilla', skills_root='skills', upstream='gos')
        backend.validate_resources('goskills-d', skills_root='skills', pool='pool')
        for method in ('vector', 'native-gos'):
            with self.assertRaisesRegex(ValueError, 'workspace'):
                backend.validate_resources(method, skills_root='skills', upstream='gos')
            backend.validate_resources(method, skills_root='skills', upstream='gos', workspace='index')

    def test_graph_and_vector_use_distinct_official_calls_and_readonly_source(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules, {'numpy': FAKE_NUMPY}), patch.object(backend, '_load_official', return_value=(Engine, Provider)):
            root = Path(d)
            source = root/'source'
            source.mkdir()
            (source/'index.bin').write_text('frozen')
            rag = backend.OfficialRetriever(root/'output', source, root/'upstream')
            graph = asyncio.run(rag.async_retrieve('visible', top_n=4, seed_top_k=5))
            vector = asyncio.run(rag.async_retrieve_vector('visible', top_n=4))
            self.assertEqual((graph.summary, vector.summary), ('graph', 'vector'))
            self.assertEqual([x[0] for x in rag.real.calls], ['graph', 'vector'])
            self.assertEqual(rag.embed.calls, 2)
            self.assertIsNone(rag.real.config.llm_service)
            self.assertFalse(rag.real.config.enable_query_rewrite)
            self.assertEqual(rag.real.config.max_context_chars, 9000)
            (root/'output/index/index.bin').write_text('mutable worker cache')
            self.assertEqual((source/'index.bin').read_text(), 'frozen')

    def test_missing_or_failed_embedding_is_not_accepted_as_lexical_fallback(self):
        class NoProviderEngine(Engine):
            async def async_retrieve_vector(self, text, **kw):
                return Result('fallback')
        class BrokenProvider:
            async def encode(self, texts):
                raise TimeoutError('private provider detail')
        class SwallowingEngine(Engine):
            async def async_retrieve_vector(self, text, **kw):
                try:
                    await self.config.embedding_service.encode([text])
                except RuntimeError:
                    pass
                return Result('fallback')
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules, {'numpy': FAKE_NUMPY}):
            root = Path(d); source = root/'source'; source.mkdir()
            for n, factory in enumerate([(NoProviderEngine, Provider), (SwallowingEngine, BrokenProvider)]):
                with patch.object(backend, '_load_official', return_value=factory):
                    rag = backend.OfficialRetriever(root/str(n), source, root/'upstream')
                    with self.assertRaisesRegex(RuntimeError, 'embedding_fallback_forbidden'):
                        asyncio.run(rag.async_retrieve_vector('goal', top_n=4))
            event = json.loads((root/'1/embedding/0001.json').read_text())
            self.assertEqual(event['error_type'], 'TimeoutError')
            self.assertNotIn('private provider detail', json.dumps(event))

    def test_embedding_dimension_guard(self):
        class WrongProvider:
            async def encode(self, texts):
                return Matrix(1, 3072)
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules, {'numpy': FAKE_NUMPY}):
            guard = backend.CheckedEmbeddings(d, WrongProvider)
            with self.assertRaisesRegex(RuntimeError, 'embedding_transport_failed'):
                asyncio.run(guard.encode(['query']))
            self.assertTrue(guard.failed)

    def test_upstream_source_pin_rejects_other_commit_and_dirty_source(self):
        with patch.object(backend.subprocess, 'check_output', return_value='0'*40), patch.object(backend.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(ValueError, 'upstream commit'):
                backend.prepare_upstream('not-imported')
        with patch.object(backend.subprocess, 'check_output', return_value=backend.OFFICIAL_COMMIT), patch.object(backend.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'tracked source'):
                backend.prepare_upstream('not-imported')

    def test_embedding_backend_cli_defaults_to_no_effect_plan(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/'not-created'
            for method in ('vector', 'native-gos'):
                proc = subprocess.run([sys.executable, '-m', 'goskills_eval.skill',
                    '--method', method, '--query', 'task', '--directory', str(output),
                    '--skills-root', 'missing-skills', '--upstream', 'missing-checkout',
                    '--workspace', 'missing-index'], cwd=ROOT/'evaluation',
                    check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(proc.stdout)['status'], 'PLAN_ONLY')
            self.assertFalse(output.exists())

    def test_actual_legacy_utils_import_uses_standard_credential_aliases(self):
        # Import the real pinned module, stubbing only its provider client and
        # retry decorator. Constructor-only: a request would fail this test.
        upstream = Path(os.environ.get('GOS_UPSTREAM', ROOT.parents[1]/'gos-baseline'))
        if not (upstream/'evaluation/utils.py').is_file():
            self.skipTest('Set GOS_UPSTREAM to exercise the optional pinned upstream import')
        package = types.ModuleType('legacy_eval_probe')
        package.__path__ = [str(upstream/'evaluation')]
        calls = []
        class Client:
            def __init__(self, **kwargs):
                calls.append(kwargs)
                self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **kw: self.fail_request()))
            def fail_request(self):
                raise AssertionError('No provider request is permitted')
        imports = {'legacy_eval_probe':package, 'openai':types.SimpleNamespace(OpenAI=Client),
                   'retry':types.SimpleNamespace(retry=lambda **kwargs: lambda fn:fn)}
        before = list(sys.path)
        try:
            with patch.dict(sys.modules, imports), patch.dict(os.environ, {'OPENAI_API_KEY':'offline-placeholder'}, clear=True), patch.object(backend.subprocess, 'check_output', return_value=backend.OFFICIAL_COMMIT), patch.object(backend.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)):
                backend.prepare_upstream(upstream)
                spec = importlib.util.spec_from_file_location('legacy_eval_probe.utils', upstream/'evaluation/utils.py')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                self.assertEqual(calls, [{'api_key':'offline-placeholder','base_url':'https://api.openai.com/v1'}])
        finally:
            sys.path[:] = before

    def test_vanilla_is_full_catalog_not_task_specific_retrieval(self):
        class SkillModule:
            def __init__(self, **kw):
                self.kw = kw
                self.root = kw['skills_dir']
                self.assertions = kw
            def get_all_full_exposure_message(self):
                return '<full_library>all skills at '+self.root+'</full_library>'
        with tempfile.TemporaryDirectory() as d, patch.object(backend, 'prepare_upstream'), patch.object(backend.importlib, 'import_module', return_value=types.SimpleNamespace(SkillModule=SkillModule)):
            root = Path(d); (root/'skills').mkdir(); (root/'gos').mkdir()
            (root/'skills/SKILL.md').write_text('synthetic skill')
            a = backend.query('vanilla', 'query A', root/'a', skills_root=root/'skills', upstream=root/'gos')
            b = backend.query('vanilla', 'different goal', root/'b', skills_root=root/'skills', upstream=root/'gos')
            self.assertEqual(a, b)
            self.assertIn('/opt/graphskills/skills', a)
            self.assertEqual(json.loads((root/'a/backend_receipt.json').read_text())['embedding_calls'], 0)

    def test_alf_baselines_keep_upstream_modes(self):
        class SkillModule:
            def __init__(self, **kw):
                self.kw = kw
        with patch('goskills_eval.skill.OfficialRetriever') as rag:
            cls = official_skill_class(SkillModule)
            for mode in ('all_full', 'vector', 'gos'):
                obj = cls(mode, Path('output'), 'skills', 'workspace', 'upstream')
                self.assertEqual(obj.mode, mode)
                self.assertEqual(obj.kw['mode'], 'none')
                self.assertFalse(obj.kw['enable_alfworld_gating'])
            self.assertEqual(rag.call_count, 2)

    def test_all_five_alf_plans_are_no_effect(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/'never-created'
            for method in backend.METHODS:
                proc = subprocess.run([sys.executable, str(ROOT/'evaluation/alfworld_run.py'),
                    '--method', method, '--upstream', 'upstream', '--config', 'config.yaml',
                    '--game-file', 'game.tw-pddl', '--skills-root', 'skills', '--pool', 'pool.json',
                    '--workspace', 'index', '--output', str(output)], check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(proc.stdout)['method'], method)
            self.assertFalse(output.exists())

    def test_game_index_resolution_is_relocatable(self):
        spec = importlib.util.spec_from_file_location('alfworld_runner_test', ROOT/'evaluation/alfworld_run.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); manifest=root/'games.json'
            manifest.write_text(json.dumps({'tasks':[{'index':7,'gamefile':'valid_unseen/episode/game.tw-pddl','game_sha256':'f'*64}]}))
            path, digest = module.resolve_game(types.SimpleNamespace(game_file=None, game_index=7, games_manifest=manifest, data_root=root/'relocated'))
            self.assertEqual(path, (root/'relocated/valid_unseen/episode/game.tw-pddl').resolve())
            self.assertEqual(digest,'f'*64)

    def test_selected_metrics_use_actual_token_and_runtime_fields(self):
        spec = importlib.util.spec_from_file_location('alfworld_metrics_test', ROOT/'evaluation/alfworld_run.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        result = {'token_usage': {'prompt_tokens':123,'completion_tokens':7}, 'agent_runtime_seconds':2.5}
        self.assertEqual(module.normalized_metrics(result), {'input_tokens':123,'output_tokens':7,'runtime_seconds':2.5})
        for invalid in (float('nan'), -1, '2.5'):
            with self.assertRaisesRegex(ValueError, 'runtime'):
                module.normalized_metrics(dict(result, agent_runtime_seconds=invalid))
        with self.assertRaises(KeyError):
            module.normalized_metrics({'token_usage':result['token_usage']})

    def test_shipped_game_manifest_and_root_containment(self):
        spec = importlib.util.spec_from_file_location('alfworld_shipped_manifest_test', ROOT/'evaluation/alfworld_run.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        manifest = ROOT/'evaluation/experiments/configs/alfworld_games.json'
        data = json.loads(manifest.read_text())
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            args = types.SimpleNamespace(game_file=None, game_index=0, games_manifest=manifest, data_root=root)
            path, digest = module.resolve_game(args)
            self.assertEqual(path, root/data['000']['path'])
            self.assertEqual(digest, data['000']['sha256'])
            unsafe = root/'unsafe.json'
            unsafe.write_text(json.dumps({'000': {'path':'../escape/game.tw-pddl'}}))
            args.games_manifest = unsafe
            with self.assertRaisesRegex(ValueError, 'within the selected data root'):
                module.resolve_game(args)

    def test_retrieval_output_overlap_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(backend, '_load_official') as load:
            root = Path(d); source=root/'workspace'; source.mkdir()
            (source/'index').write_text('original')
            with self.assertRaisesRegex(ValueError, 'separate from input workspace'):
                backend.OfficialRetriever(source/'output', source, root/'upstream')
            self.assertEqual(sorted(p.name for p in source.iterdir()), ['index'])
            with self.assertRaisesRegex(ValueError, 'separate from input workspace'):
                backend.OfficialRetriever(root, source, root/'upstream')
            load.assert_not_called()
            for key in ('skills_root', 'pool', 'workspace', 'upstream', 'game_file', 'config'):
                with self.assertRaisesRegex(ValueError, 'separate from input'):
                    backend.validate_output(source/'output', **{key:source})
            self.assertFalse((source/'output').exists())

if __name__ == '__main__':
    unittest.main()
