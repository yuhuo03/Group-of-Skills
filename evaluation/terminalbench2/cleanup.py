"""Reconcile only an exited main container owned by the completed TB2 trial.

Lifecycle observation follows the historical convergence hook. No running
container is stopped/killed, no force/volume deletion is used, and every removal
rechecks the full ID, exact Compose project/service and stopped state.
"""
import json
from pathlib import Path
import re
import subprocess
import time

ID = re.compile('[0-9a-f]{64}')
PROJECT = re.compile('[a-z0-9][a-z0-9_-]{1,180}')


class CleanupRefused(RuntimeError):
    pass


def stopped(project, cid):
    return {'id': cid, 'project': project, 'service': 'main', 'status': 'exited',
            'running': False, 'pid': 0, 'dead': False}


def is_stopped(state, project, cid):
    return (isinstance(state, dict) and state == stopped(project, cid) and
            type(state['running']) is bool and type(state['dead']) is bool and
            type(state['pid']) is int)


class DockerBackend:
    def __init__(self, project, cid, run=None):
        if not PROJECT.fullmatch(project) or not ID.fullmatch(cid):
            raise CleanupRefused('invalid_owned_identity')
        self.project, self.cid = project, cid
        self.run = subprocess.run if run is None else run

    def _run(self, args):
        try:
            result = self.run(['docker', *args], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return 1, b''
        if not isinstance(result.stdout, bytes) or len(result.stdout) > 65536:
            return 1, b''
        return result.returncode, result.stdout

    def query(self):
        rc, out = self._run(['ps', '-aq', '--no-trunc', '--filter',
                             'label=com.docker.compose.project=' + self.project])
        try:
            ids = out.decode('ascii').split()
        except UnicodeError:
            return 1, []
        if any(not ID.fullmatch(cid) for cid in ids) or len(ids) != len(set(ids)):
            return 1, []
        return rc, ids

    def inspect(self):
        template = ('{"id":{{json .Id}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
                    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
                    '"status":{{json .State.Status}},"running":{{json .State.Running}},'
                    '"pid":{{json .State.Pid}},"dead":{{json .State.Dead}}}')
        rc, out = self._run(['inspect', '--format', template, self.cid])
        try:
            state = json.loads(out)
        except (ValueError, UnicodeError):
            return 1, {}
        return rc, state

    def remove_stopped(self):
        rc, state = self.inspect()
        if rc or not is_stopped(state, self.project, self.cid):
            raise CleanupRefused('stopped_state_changed_before_removal')
        rc, _ = self._run(['rm', self.cid])
        if rc:
            raise CleanupRefused('nonforce_removal_failed')


def observe(backend, emit, clock=time.monotonic, sleep=time.sleep):
    deadline, stable = clock() + 90, 0
    expected = stopped(backend.project, backend.cid)
    for attempt in range(6):
        if clock() >= deadline:
            break
        rc, ids = backend.query()
        if rc:
            emit({'attempt': attempt, 'category': 'query_failed'}); stable = 0
        elif set(ids) - {backend.cid}:
            raise CleanupRefused('unexpected_owned_identity')
        elif not ids:
            emit({'attempt': attempt, 'category': 'already_absent'})
            return
        else:
            if clock() >= deadline:
                break
            rc, state = backend.inspect()
            if rc:
                emit({'attempt': attempt, 'category': 'inspect_failed'}); stable = 0
            else:
                if (not isinstance(state, dict) or set(state) != set(expected) or
                        any(state[k] != expected[k] for k in ('id','project','service'))):
                    raise CleanupRefused('identity_or_schema_mismatch')
                if type(state['running']) is not bool or type(state['dead']) is not bool or type(state['pid']) is not int or state['pid'] < 0:
                    raise CleanupRefused('invalid_state_types')
                if state['dead'] or state['status'] not in {'created','running','restarting','paused','exited'}:
                    raise CleanupRefused('unsupported_lifecycle')
                is_stopped = state == expected
                emit({'attempt': attempt, 'category': 'stopped' if is_stopped else 'waiting_lifecycle',
                      'status': state['status'], 'running': state['running'], 'pid': state['pid']})
                stable = stable + 1 if is_stopped else 0
                if stable == 2 and clock() < deadline:
                    return
        if attempt < 5 and clock() < deadline:
            sleep(min(2, max(0, deadline - clock())))
    raise CleanupRefused('convergence_exhausted')


def reconcile(backend):
    # An ABSENT observation is not permission to remove a newly appeared ID.
    rc, ids = backend.query()
    if rc or set(ids) - {backend.cid}:
        raise CleanupRefused('query_failed_or_unexpected_identity')
    removed = []
    if ids:
        rc, state = backend.inspect()
        if rc or not is_stopped(state, backend.project, backend.cid):
            raise CleanupRefused('identity_or_stopped_state_mismatch')
        backend.remove_stopped()
        removed.append(backend.cid)
    rc, ids = backend.query()
    if rc or ids:
        raise CleanupRefused('owned_containers_not_confirmed_clear')
    return {'owned_clear': True, 'removed_ids': removed}


def reconcile_trial(project, evidence_path, *, run=None, clock=time.monotonic, sleep=time.sleep):
    """Called only after the owned trial finished and result assessment passed."""
    run = subprocess.run if run is None else run
    # Reserve evidence before Docker calls. Never overwrite a previous cleanup.
    with Path(evidence_path).open('x', encoding='utf-8') as evidence:
        def emit(row):
            evidence.write(json.dumps(row, sort_keys=True) + '\n'); evidence.flush()
        try:
            if not isinstance(project, str) or not PROJECT.fullmatch(project):
                raise CleanupRefused('invalid_trial_project')
            try:
                result = run(['docker', 'ps', '-aq', '--no-trunc', '--filter',
                              'label=com.docker.compose.project=' + project],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
            except (OSError, subprocess.TimeoutExpired):
                raise CleanupRefused('owned_query_failed') from None
            if result.returncode or not isinstance(result.stdout, bytes) or len(result.stdout) > 1024:
                raise CleanupRefused('owned_query_failed')
            try:
                ids = result.stdout.decode('ascii').split()
            except UnicodeError:
                raise CleanupRefused('owned_query_invalid') from None
            if not ids:
                emit({'status': 'CLEAR', 'stage': 'discovery'})
                return {'owned_clear': True, 'removed_ids': []}
            if len(ids) != 1 or not ID.fullmatch(ids[0]):
                raise CleanupRefused('unexpected_owned_container_set')
            backend = DockerBackend(project, ids[0], run)
            observe(backend, emit, clock, sleep)
            result = reconcile(backend)
            emit({'status': 'CLEAR', 'stage': 'strict_reconcile'})
            return result
        except CleanupRefused as exc:
            emit({'status': 'REFUSED', 'category': str(exc)})
            raise
