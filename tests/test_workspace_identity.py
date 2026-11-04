"""Trusted export/source consistency checks without deserialization or APIs."""
from pathlib import Path
import copy
import json
import shutil
import subprocess
import sys
from unittest.mock import patch
import pytest
from goskills.groups import build_pool
from goskills.config import validate_config
from goskills_eval.workspace import bind_workspace, validate_workspace, identity_path
from goskills_eval.skill import query, OfficialRetriever
from workspace_fixture import make_workspace


def fixture(root):
    library = root/'skills'
    for name in ['a','b']:
        (library/name).mkdir(parents=True)
        (library/name/'SKILL.md').write_text('# '+name+'\nSynthetic source\n')
    workspace = root/'workspace'
    graph = make_workspace(workspace, library)
    pool = root/'pool.json'
    pool.write_text(json.dumps(build_pool(graph, validate_config())))
    return workspace, library, graph, pool


def test_consistent_workspace_pool_and_library_survive_relocation(tmp_path):
    source=tmp_path/'source';source.mkdir()
    workspace,library,graph,pool=fixture(source)
    receipt=validate_workspace(workspace,library,pool=pool)
    assert receipt['source_document_count']==2
    moved=tmp_path/'moved';shutil.copytree(source,moved)
    assert validate_workspace(moved/'workspace',moved/'skills',pool=moved/'pool.json')==receipt
    changed=copy.deepcopy(graph)
    changed['edges']=[{'source':'a/SKILL.md','target':'b/SKILL.md','type':'workflow','weight':1}]
    other=tmp_path/'other.json';other.write_text(json.dumps(build_pool(changed,validate_config())))
    with pytest.raises(ValueError,match='different graph exports'):
        validate_workspace(workspace,library,pool=other)


@pytest.mark.parametrize('mutation',['skill','auxiliary','extra','index','graph','symlink','binding'])
def test_mismatch_rejected_before_provider_import_and_output(tmp_path,mutation):
    workspace,library,_,_=fixture(tmp_path)
    if mutation=='skill':(library/'a/SKILL.md').write_text('changed')
    elif mutation=='auxiliary':(library/'a/helper.py').write_text('changed auxiliary file')
    elif mutation=='extra':(library/'SKILL.md').write_text('extra skill')
    elif mutation=='index':(workspace/'entities_hnsw_index_1536.bin').write_bytes(b'changed')
    elif mutation=='graph':(workspace/'graph_igraph_data.pklz').write_bytes(b'changed')
    elif mutation=='symlink':(workspace/'outside').symlink_to(library/'a/SKILL.md')
    else:identity_path(workspace).unlink()
    for method in ('vector','native-gos'):
        with patch('goskills_eval.skill._load_official') as load:
            with pytest.raises(ValueError):
                query(method,'visible goal',tmp_path/method,skills_root=library,
                      workspace=workspace,upstream=tmp_path)
            load.assert_not_called()
            assert not (tmp_path/method).exists()


def test_bind_cli_is_local_and_never_overwrites(tmp_path):
    workspace,library,_,_=fixture(tmp_path)
    existing=identity_path(workspace).read_bytes()
    with pytest.raises(FileExistsError):
        bind_workspace(tmp_path/'workspace.graph.json',workspace,library)
    assert identity_path(workspace).read_bytes()==existing
    copy=tmp_path/'copy';shutil.copytree(workspace,copy)
    result=subprocess.run([sys.executable,'-m','goskills_eval.workspace','bind',
                           '--graph',str(tmp_path/'workspace.graph.json'),
                           '--workspace',str(copy),'--skills-root',str(library)],
                          cwd=tmp_path,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['provider_calls']==0
    assert validate_workspace(copy,library)==validate_workspace(workspace,library)


def test_changes_since_export_and_wrong_model_are_not_rebound(tmp_path):
    workspace,library,graph,_=fixture(tmp_path)
    identity_path(workspace).unlink()
    export=tmp_path/'workspace.graph.json'
    changed=copy.deepcopy(graph);changed['provenance']['dim']=3072
    export.write_text(json.dumps(changed))
    with pytest.raises(ValueError,match='1536'):bind_workspace(export,workspace,library)
    export.write_text(json.dumps(graph));(library/'a/SKILL.md').write_text('wrong source')
    with pytest.raises(ValueError,match='mismatch'):bind_workspace(export,workspace,library)
    assert not identity_path(workspace).exists()


def test_native_pool_also_binds_auxiliary_library_files(tmp_path):
    from goskills_eval.assets import validate_library
    _,library,_,pool=fixture(tmp_path)
    assert validate_library(pool,library)['source_documents']==2
    (library/'a/helper.py').write_text('new auxiliary implementation')
    with pytest.raises(ValueError,match='auxiliary-file'):
        validate_library(pool,library)


def test_workspace_copy_race_rejected_before_provider_creation(tmp_path):
    workspace,library,_,_=fixture(tmp_path)
    original=shutil.copytree
    def changed_copy(source,dest):
        original(source,dest)
        (dest/'graph_igraph_data.pklz').write_bytes(b'changed during copy')
    with patch('goskills_eval.skill._load_official') as load,patch('goskills_eval.skill.shutil.copytree',side_effect=changed_copy):
        load.return_value=(object(),object())
        with pytest.raises(ValueError,match='changed while'):
            OfficialRetriever(tmp_path/'query',workspace,tmp_path/'upstream',library)
