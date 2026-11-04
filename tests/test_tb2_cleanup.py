"""Owned-container lifecycle transitions with a fake bounded Docker transport."""
import json
from types import SimpleNamespace
import pytest
from goskills_eval.terminalbench2.cleanup import CleanupRefused, reconcile_trial, stopped

CID='a'*64
PROJECT='trial-test__env'


class Docker:
    def __init__(self, states=None, queries=None):
        self.states=list(states or [stopped(PROJECT,CID)])
        self.queries=list(queries or [])
        self.calls=[];self.removed=False

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        assert kwargs['timeout']==15 and not kwargs.get('shell')
        if command[1]=='ps':
            assert command[-1]=='label=com.docker.compose.project='+PROJECT
            ids=self.queries.pop(0) if self.queries else ([] if self.removed else [CID])
            return SimpleNamespace(returncode=0,stdout=('\n'.join(ids)).encode())
        if command[1]=='inspect':
            assert command[-1]==CID and command[2]=='--format'
            assert '.Config.Env' not in command[3] and '.Config.Cmd' not in command[3]
            state=self.states.pop(0) if len(self.states)>1 else self.states[0]
            return SimpleNamespace(returncode=0,stdout=json.dumps(state).encode())
        assert command==['docker','rm',CID]
        self.removed=True
        return SimpleNamespace(returncode=0,stdout=b'')


def run(tmp_path,docker):
    return reconcile_trial(PROJECT,tmp_path/'evidence.jsonl',run=docker,
                           clock=lambda:0,sleep=lambda _:None)


def test_running_then_two_stopped_observations_and_nonforce_removal(tmp_path):
    running=stopped(PROJECT,CID)|{'status':'running','running':True,'pid':123}
    docker=Docker([running,stopped(PROJECT,CID)])
    assert run(tmp_path,docker)=={'owned_clear':True,'removed_ids':[CID]}
    assert docker.removed
    assert all('-f' not in c and '--force' not in c and '-v' not in c for c in docker.calls)
    rows=[json.loads(x) for x in (tmp_path/'evidence.jsonl').read_text().splitlines()]
    assert rows[0]['category']=='waiting_lifecycle' and rows[-1]['status']=='CLEAR'
    calls=len(docker.calls)
    with pytest.raises(FileExistsError):run(tmp_path,docker)
    assert len(docker.calls)==calls


@pytest.mark.parametrize('state',[
    stopped(PROJECT,CID)|{'status':'running','running':True,'pid':123},
    stopped(PROJECT,CID)|{'project':'someone-else'},
    stopped(PROJECT,CID)|{'service':'sidecar'},
    stopped(PROJECT,CID)|{'id':'b'*64},
    stopped(PROJECT,CID)|{'dead':True},
    stopped(PROJECT,CID)|{'running':0},
    stopped(PROJECT,CID)|{'private':'DO_NOT_EMIT'},
])
def test_never_deletes_live_foreign_or_malformed_state(tmp_path,state):
    docker=Docker([state])
    with pytest.raises(CleanupRefused):run(tmp_path,docker)
    assert not docker.removed
    assert 'DO_NOT_EMIT' not in (tmp_path/'evidence.jsonl').read_text()
    assert len([x for x in docker.calls if x[1]=='inspect'])<=6


def test_boundary_state_change_refused_after_successful_observation(tmp_path):
    running=stopped(PROJECT,CID)|{'status':'running','running':True,'pid':123}
    # Two observer reads, one reconciliation read, then the mutation guard.
    docker=Docker([stopped(PROJECT,CID)]*3+[running])
    with pytest.raises(CleanupRefused,match='changed_before_removal'):run(tmp_path,docker)
    assert not docker.removed


def test_disappeared_observation_does_not_authorize_a_new_identity(tmp_path):
    docker=Docker(queries=[[CID],[],['b'*64]])
    with pytest.raises(CleanupRefused,match='unexpected_identity'):run(tmp_path,docker)
    assert not docker.removed


def test_empty_owned_query_and_multiple_container_refusal(tmp_path):
    docker=Docker(queries=[[]])
    assert run(tmp_path,docker)['owned_clear']
    assert len(docker.calls)==1
    other=tmp_path/'other';other.mkdir();docker=Docker(queries=[[CID,'b'*64]])
    with pytest.raises(CleanupRefused,match='unexpected_owned_container_set'):run(other,docker)
    assert len(docker.calls)==1 and not docker.removed


def test_failed_query_never_interpreted_as_empty(tmp_path):
    def fail(*args,**kwargs):return SimpleNamespace(returncode=1,stdout=b'PRIVATE_STDOUT')
    with pytest.raises(CleanupRefused,match='owned_query_failed'):run(tmp_path,fail)
    assert 'PRIVATE' not in (tmp_path/'evidence.jsonl').read_text()
