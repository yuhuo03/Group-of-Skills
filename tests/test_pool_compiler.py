"""Public pool compiler: exact data/query parity and fail-closed cache reads."""
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import pytest
from goskills import retrieval
from goskills.config import canonical_hash, validate_config
from goskills.groups import build_pool
from goskills_eval.compiled_pool import retriever, compile_pool
from test_compiled_pool import compile_fixture


def test_public_compiler_preserves_all_maps_and_query_outputs(tmp_path):
    graph=json.loads((Path(__file__).parent/'fixtures/minimal_graph.json').read_text())
    pool=build_pool(graph,validate_config())
    source=tmp_path/'pool.json';source.write_text(json.dumps(pool));before=source.read_bytes()
    directory=tmp_path/'cache'
    receipt=compile_pool(source,directory)
    assert receipt['original_pool_hash']==canonical_hash(pool)
    assert source.read_bytes()==before
    with sqlite3.connect(directory/'maps.sqlite') as db:
        for kind in ('skills','groups','facet_index','member_index'):
            assert {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM maps WHERE kind=?',(kind,))}==pool[kind]
    normal=retrieval.Retriever(pool,source_root='/skills')
    disk=retriever(directory,'/skills')
    for query in ['parse geometry JSON','validate output format','unrelated task','write CSV']:
        assert disk.query(query)==normal.query(query)
    with pytest.raises(FileExistsError):compile_pool(source,directory)
    pool['skills'][next(iter(pool['skills']))]['text']='modified without rebuilding'
    source.write_text(json.dumps(pool))
    with pytest.raises(ValueError,match='hash mismatch'):compile_pool(source,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_compiler_cli_and_optimized_python_reject_corruption(tmp_path):
    graph=json.loads((Path(__file__).parent/'fixtures/minimal_graph.json').read_text())
    source=tmp_path/'pool.json';source.write_text(json.dumps(build_pool(graph,validate_config())))
    directory=tmp_path/'cache'
    result=subprocess.run([sys.executable,'-m','goskills_eval.compiled_pool','compile',
                           '--pool',str(source),'--output',str(directory)],cwd=tmp_path,
                          capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['status']=='COMPILED_EXACT'
    (directory/'header.json').write_text('{}')
    # Integrity checks must still run under python -O (no assert-based guard).
    result=subprocess.run([sys.executable,'-O','-m','goskills_eval.compiled_pool',
                           '--cache',str(directory),'--query','test','--source-root','/skills'],
                          cwd=tmp_path,capture_output=True,text=True,timeout=20)
    assert result.returncode!=0 and 'hash mismatch' in result.stderr


@pytest.mark.parametrize('mutation',['missing_cache','extra_path','missing_core','status'])
def test_compiled_receipt_cannot_skip_verification(tmp_path,mutation):
    compile_fixture(tmp_path/'cache')
    receipt=tmp_path/'cache/RECEIPT.json';data=json.loads(receipt.read_text())
    if mutation=='missing_cache':data['files'].pop('header.json')
    elif mutation=='extra_path':data['files']['../outside']='0'*64
    elif mutation=='missing_core':data['core_sources']={}
    else:data['status']='INCOMPLETE'
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError):retriever(tmp_path/'cache','/skills')
