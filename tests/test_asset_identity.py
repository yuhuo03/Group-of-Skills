"""Asset mismatch must fail before any model call or benchmark execution."""
import hashlib
import json
from pathlib import Path
import pytest
from goskills.groups import build_pool
from goskills.config import validate_config
from goskills_eval.assets import validate_library
from goskills_eval.skill import query, validate_resources
from test_compiled_pool import compile_fixture


def fixture(tmp_path, native=False):
    graph=json.loads((Path(__file__).parent/'fixtures/minimal_graph.json').read_text())
    library=tmp_path/'library';library.mkdir()
    for skill in graph['skills']:
        raw=skill['text'].encode()
        if native:
            raw=b'---\nname: example\n---\r\n'+raw
            skill['text']=raw.decode()
            skill['metadata']['source_sha256']=hashlib.sha256(raw).hexdigest()
        p=library/skill['source_path'];p.parent.mkdir();p.write_bytes(raw)
    pool=tmp_path/'pool.json';pool.write_text(json.dumps(build_pool(graph,validate_config())))
    return pool,library


@pytest.mark.parametrize('native',[False,True])
def test_full_source_identity_and_container_path_are_independent(tmp_path,native):
    pool,library=fixture(tmp_path,native)
    result=validate_library(pool,library)
    assert result['source_documents']==5
    text=query('goskills-d','Parse STL and output JSON',tmp_path/'query',
               skills_root=library,pool=pool,source_root='/container/skills')
    assert '/container/skills/' in text
    (library/'mesh/SKILL.md').write_text('Changed source')
    with pytest.raises(ValueError,match='mismatch'):
        query('goskills-d','Parse STL',tmp_path/'bad',skills_root=library,pool=pool)
    assert not (tmp_path/'bad').exists()


@pytest.mark.parametrize('mutation',['missing','extra','symlink','directory_symlink'])
def test_membership_and_symlinks_rejected(tmp_path,mutation):
    pool,library=fixture(tmp_path)
    if mutation=='missing':(library/'mesh/SKILL.md').unlink()
    elif mutation=='extra':(library/'SKILL.md').write_text('extra')
    elif mutation=='symlink':
        path=library/'mesh/SKILL.md';path.unlink();path.symlink_to(library/'check/SKILL.md')
    else:(library/'linked').symlink_to(library/'mesh',target_is_directory=True)
    with pytest.raises(ValueError):
        validate_resources('goskills-d',pool=pool,skills_root=library,check_files=True)


def test_compiled_pool_gets_same_source_checks(tmp_path):
    pool=compile_fixture(tmp_path/'compiled')
    library=tmp_path/'library';library.mkdir()
    for skill in pool['skills'].values():
        p=library/skill['source_path'];p.parent.mkdir();p.write_text(skill['text'])
    assert validate_library(tmp_path/'compiled',library)['source_documents']==5
    (library/'mesh/SKILL.md').write_text('Wrong library')
    with pytest.raises(ValueError,match='mismatch'):
        validate_library(tmp_path/'compiled',library)


def test_campaign_validates_later_method_before_dispatch(tmp_path):
    from test_campaign import CampaignTests, script
    from goskills_eval.experiments.run import build_plan
    config=CampaignTests().fixture(tmp_path)
    (tmp_path/'skills/a/SKILL.md').write_text('wrong source')
    with pytest.raises(ValueError,match='mismatch'):
        build_plan(config,'tb2',['noskills','goskills-d'],tmp_path/'out')
    assert not (tmp_path/'out').exists()
    rows=script('doctor').check(config)['checks']
    assert not next(r for r in rows if r['check']=='pool_library_identity')['ok']
