"""Disk-backed pools preserve JSON retrieval without changing shared policy globals."""
import json
from pathlib import Path
import sqlite3
from goskills import retrieval
from goskills.config import canonical_hash, validate_config
from goskills.groups import build_pool
from goskills_eval.compiled_pool import retriever, digest


def compile_fixture(root):
    root.mkdir()
    graph=json.loads((Path(__file__).parent/'fixtures/minimal_graph.json').read_text())
    pool=build_pool(graph, validate_config())
    header=dict(pool)
    with sqlite3.connect(root/'maps.sqlite') as db:
        db.execute('CREATE TABLE maps (kind TEXT, key TEXT, value TEXT, PRIMARY KEY (kind,key))')
        for kind in ['skills','groups','facet_index','member_index']:
            mapping=header.pop(kind)
            db.executemany('INSERT INTO maps VALUES (?,?,?)',[(kind,k,json.dumps(v)) for k,v in mapping.items()])
    with sqlite3.connect(root/'adjacency.sqlite') as db:
        db.execute('CREATE TABLE adjacency (key TEXT PRIMARY KEY, value TEXT)')
        db.executemany('INSERT INTO adjacency VALUES (?,?)',[(k,json.dumps(v)) for k,v in header.pop('adjacency').items()])
    (root/'header.json').write_text(json.dumps(header))
    receipt={'status':'COMPILED_EXACT','original_pool_hash':canonical_hash(pool),
             'files':{n:digest(root/n) for n in ['maps.sqlite','adjacency.sqlite','header.json']},
             'core_sources':{p.name:digest(p) for p in Path(retrieval.__file__).parent.glob('*.py')}}
    (root/'RECEIPT.json').write_text(json.dumps(receipt))
    return pool


def test_compiled_and_regular_pools_do_not_share_patched_globals(tmp_path):
    pool=compile_fixture(tmp_path/'cache')
    before_hash=retrieval.canonical_hash;before_validate=retrieval.validate_pool
    try:
        disk=retriever(tmp_path/'cache','/skills')
        assert retrieval.canonical_hash is before_hash
        assert retrieval.validate_pool is before_validate
        normal=retrieval.Retriever(pool,source_root='/skills')
        for query in ['parse geometry JSON','validate output format']:
            assert disk.query(query)==normal.query(query)
    finally:
        retrieval.canonical_hash=before_hash;retrieval.validate_pool=before_validate


def test_sqlite_cache_path_with_uri_characters(tmp_path):
    directory=tmp_path/'cache #1? ready'
    pool=compile_fixture(directory)
    before_hash=retrieval.canonical_hash;before_validate=retrieval.validate_pool
    try:
        assert retriever(directory,'/skills').query('parse JSON')==retrieval.Retriever(pool,source_root='/skills').query('parse JSON')
    finally:
        retrieval.canonical_hash=before_hash;retrieval.validate_pool=before_validate
