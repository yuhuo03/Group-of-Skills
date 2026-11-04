import json
from pathlib import Path

import pytest

from goskills.config import validate_config
from goskills.groups import build_pool
from goskills.io import read_json
from goskills.retrieval import Retriever
from goskills.validation import validate_bundle
from goskills_eval.experiments import skillsets, scale, prepare_ablations
from goskills_eval.experiments.ablation_conditions import CONDITIONS, build_condition
from goskills_eval.experiments.scheduler import load_plan, resume_campaign
from goskills_eval.experiments.bindings import verify_bindings
from goskills_eval.runtime import METHODS
import test_campaign as campaign_tests
from workspace_fixture import make_workspace


def library(tmp_path):
    root = tmp_path/'source'
    root.mkdir()
    for name in ['a', 'b', 'c']:
        directory = root/name
        directory.mkdir()
        (directory/'SKILL.md').write_text('name: '+name+'\nSynthetic skill.\n')
        (directory/'helper.py').write_text('# helper '+name+'\n')
    (root/'LICENSE').write_text('Synthetic attribution.\n')
    return root


def test_nested_skillsets_preserve_required_members_auxiliary_and_license(tmp_path):
    source = library(tmp_path)
    output = tmp_path/'sets'
    plan = skillsets.prepare(source, output, [3, 1, 2], ['c'])
    assert not output.exists()
    assert [list(row['members']) for row in plan['libraries']] == [['c'], ['c', 'a'], ['c', 'a', 'b']]
    assert skillsets.prepare(source, output, [3, 1, 2], ['c'], execute=True) == plan
    for row in plan['libraries']:
        dest = output/row['directory']
        assert (dest/'LICENSE').read_bytes() == (source/'LICENSE').read_bytes()
        for name, files in row['members'].items():
            assert skillsets.member_files(dest/name) == files
    assert (output/'COMPLETE.json').exists()
    with pytest.raises(FileExistsError):
        skillsets.prepare(source, output, [1], execute=True)


@pytest.mark.parametrize('sizes,required', [([4], []), ([1, 1], []), ([True], []), ([1], ['z']),
                                          ([1], ['a', 'b']), ([2], ['a', 'a'])])
def test_invalid_skillsets_do_not_write(tmp_path, sizes, required):
    source = library(tmp_path)
    with pytest.raises(ValueError):
        skillsets.prepare(source, tmp_path/'out', sizes, required, execute=True)
    assert not (tmp_path/'out').exists()


def test_skillset_rejects_symlink_nested_skill_and_private_env(tmp_path):
    source = library(tmp_path)
    link = source/'a'/'linked'
    link.symlink_to(source/'b'/'SKILL.md')
    with pytest.raises(ValueError, match='symlink'):
        skillsets.prepare(source, tmp_path/'out', [1])
    link.unlink()
    (source/'a'/'.env').write_text('SECRET=synthetic-only')
    with pytest.raises(ValueError, match='private'):
        skillsets.prepare(source, tmp_path/'out', [1])
    (source/'a'/'.env').unlink()
    nested = source/'a'/'nested'
    nested.mkdir()
    (nested/'SKILL.md').write_text('nested')
    with pytest.raises(ValueError, match='top-level'):
        skillsets.prepare(source, tmp_path/'out', [1])


def scale_fixture(tmp_path):
    config = campaign_tests.CampaignTests().fixture(tmp_path)
    cfg = read_json(config)
    larger = tmp_path/'larger'
    import shutil
    shutil.copytree(tmp_path/'skills', larger)
    (larger/'b').mkdir()
    (larger/'b'/'SKILL.md').write_text('---\nname: b\ndescription: synthetic\n---\nSecond test skill.\n')
    graph = make_workspace(tmp_path/'workspace2', larger)
    (tmp_path/'pool2.json').write_text(json.dumps(build_pool(graph, validate_config())))
    cfg2 = {**cfg, 'skills_root': 'larger', 'workspace': 'workspace2', 'pool': 'pool2.json'}
    (tmp_path/'large.json').write_text(json.dumps(cfg2))
    manifest = tmp_path/'scales.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'membership': 'nested',
                         'libraries': [{'size': 2, 'config': 'large.json'}, {'size': 1, 'config': 'local.json'}]}))
    return manifest


def test_scale_checks_all_five_methods_and_saves_runnable_unclaimed_plans(tmp_path):
    manifest = scale_fixture(tmp_path)
    plan = scale.matrix(manifest, tmp_path/'runs', 'tb2', list(METHODS), workers=2, per_method=1)
    assert not (tmp_path/'runs').exists()
    assert [p['scale']['size'] for p in plan['campaigns']] == [1, 2]
    assert sum(p['count'] for p in plan['campaigns']) == 10
    scale.prepare(plan)
    for campaign in plan['campaigns']:
        assert load_plan(campaign['output']) == campaign
        assert resume_campaign(campaign['output'])['never_claimed'] == 5
        verify_bindings(campaign)
    # Membership manifest is bound as well as all task/library/code inputs.
    manifest.write_text('{}')
    with pytest.raises(ValueError, match='inputs changed'):
        resume_campaign(plan['campaigns'][0]['output'])


@pytest.mark.parametrize('change', ['size', 'membership', 'task', 'runtime'])
def test_scale_refuses_unmatched_comparisons_before_output(tmp_path, change):
    manifest = scale_fixture(tmp_path)
    if change == 'size':
        data = read_json(manifest)
        data['libraries'][0]['size'] = 3
        manifest.write_text(json.dumps(data))
    elif change == 'membership':
        (tmp_path/'larger'/'a'/'helper').write_text('different auxiliary file')
    else:
        cfg = read_json(tmp_path/'large.json')
        if change == 'runtime':
            cfg['runtime'] = {'profile': 'custom', 'model': 'test-model', 'expected_model': 'test-response'}
        else:
            import shutil
            shutil.copytree(tmp_path/'tasks', tmp_path/'different-tasks')
            (tmp_path/'different-tasks/sample/instruction.md').write_text('Different benchmark input')
            cfg['tb2']['tasks_root'] = 'different-tasks'
        (tmp_path/'large.json').write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        scale.matrix(manifest, tmp_path/'runs', 'tb2', ['noskills'])
    assert not (tmp_path/'runs').exists()


def test_component_conditions_preserve_full_policy_sources_and_budgets(tmp_path):
    graph = read_json(Path(__file__).parent/'fixtures/minimal_graph.json')
    base = build_pool(graph, validate_config())
    assert build_condition(graph, 'full') == base
    assert len(base['group_edges']) > 0
    for name in CONDITIONS:
        pool = build_condition(graph, name)
        assert pool['skills'] == base['skills']
        for key in ['top_n', 'max_skill_chars', 'max_context_chars']:
            assert pool['config'][key] == base['config'][key]
        bundle = Retriever(pool).query('Extract CSV tables from PDF and validate the output')
        validate_bundle(bundle)
        if name == 'singleton-groups':
            assert all(len(g['members']) == 1 for g in pool['groups'].values())
        if name == 'single-group-plan':
            assert len(bundle['plan']) <= 1
        if name == 'no-coverage-backfill':
            assert bundle['trace']['backfill_steps'] == []
        if name == 'no-group-graph':
            assert pool['group_edges'] == [] and all(not edges for edges in pool['adjacency'].values())
            assert pool['groups'] == base['groups']
        if name != 'full':
            assert pool['provenance']['experiment']['historical_paper_replication'] is False


def test_prepare_components_and_compile_for_actual_query(tmp_path):
    from test_asset_identity import fixture
    from goskills_eval.compiled_pool import compile_pool
    from goskills_eval.retrieval import DContext
    pool, library_path = fixture(tmp_path)
    graph = read_json(Path(__file__).parent/'fixtures/minimal_graph.json')
    path = tmp_path/'graph.json'
    path.write_text(json.dumps(graph))
    # fixture writes the graph's complete text to the library.
    out = tmp_path/'components'
    prepare_ablations.prepare(path, library_path, out, list(CONDITIONS), execute=True)
    from goskills_eval.assets import validate_library
    for name in CONDITIONS:
        validate_library(out/(name+'.json'), library_path)
    compile_pool(out/'no-group-graph.json', tmp_path/'compiled')
    bundle = DContext(tmp_path/'compiled').query('Extract CSV from PDF')
    assert bundle['provenance']['experiment']['condition'] == 'no-group-graph'
    assert bundle['trace']['support_steps'] is not None
