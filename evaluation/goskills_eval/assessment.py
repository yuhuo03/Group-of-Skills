"""Shared numeric accounting for newly executed trials; no missing-value zeros."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import math


def normalize_metrics(result, receipt=None):
    """Read recorded agent metrics, independently of the reward's success value.

    Task/agent adapters must first validate model, transport, verifier and cleanup.
    Missing duration or token evidence raises; it is never filled with zero.
    """
    receipt = receipt or {}
    usage = receipt.get('token_usage') or {}
    if not usage:
        agent = result.get('agent_result') or {}
        usage = {'input': agent.get('n_input_tokens'),
                 'output': agent.get('n_output_tokens'),
                 'cached': agent.get('n_cache_tokens')}
    normalized = {}
    for source, target in [('input', 'input_tokens'), ('output', 'output_tokens')]:
        value = usage.get(source)
        if type(value) is not int or value < 0:
            raise ValueError('missing_or_invalid_' + target)
        normalized[target] = value
    cached = usage.get('cached')
    if cached is not None:
        if type(cached) is not int or cached < 0 or cached > normalized['input_tokens']:
            raise ValueError('invalid_cached_tokens')
        normalized['cached_tokens'] = cached
    execution = result.get('agent_execution') or {}
    if execution.get('started_at') and execution.get('finished_at'):
        start = datetime.fromisoformat(execution['started_at'].replace('Z', '+00:00'))
        finish = datetime.fromisoformat(execution['finished_at'].replace('Z', '+00:00'))
        duration = (finish - start).total_seconds()
    else:
        duration = result.get('agent_runtime_seconds')
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
        raise ValueError('missing_or_invalid_agent_runtime')
    normalized['runtime_seconds'] = duration
    return normalized


def assess_trial(trial_directory, method, binary=True, *, require_retrieval=None):
    """Original model/transport/score gates plus canonical report evidence.

    This function does not turn missing reports, setup failures or null rewards
    into valid zeros. Container cleanup is checked by the runner separately.
    """
    td = Path(trial_directory)
    read = lambda path: json.loads(path.read_text())
    result = read(td / 'result.json')
    receipt = read(td / 'agent/agent_receipt.json')
    if receipt.get('method') != method:
        raise ValueError('agent_method_mismatch')
    if not receipt.get('api_calls') or receipt.get('actual_models') != ['gpt-5.4-2026-03-05'] or receipt.get('transport_fatal'):
        raise ValueError('agent_model_or_transport_failed')
    if receipt.get('finish_status') not in {'completed', 'max_turns', 'agent_timeout'}:
        raise ValueError('agent_failed')
    if require_retrieval is None:
        require_retrieval = method != 'noskills'
    if require_retrieval:
        if not receipt.get('successful_retrievals') or receipt['successful_retrievals'] != receipt.get('retrieval_count'):
            raise ValueError('retrieval_evidence_missing')
        receipts = list((td / 'agent/retrievals').glob('*/receipt.json'))
        if len(receipts) != receipt['successful_retrievals'] or any(read(p).get('status') != 'PASSED' for p in receipts):
            raise ValueError('retrieval_receipt_missing')
    exception = result.get('exception_info') or {}
    if exception and exception.get('exception_type') != 'AgentTimeoutError':
        raise ValueError('trial_exception')
    reward = ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward')
    if type(reward) not in (int, float) or not math.isfinite(reward) or not 0 <= reward <= 1 or (binary and reward not in (0, 1)):
        raise ValueError('missing_or_invalid_reward')
    report = read(td / 'verifier/ctrf.json').get('results', {})
    if not report.get('tests') or len(report['tests']) != report.get('summary', {}).get('tests'):
        raise ValueError('canonical_tests_not_executed')
    calls = read(td / 'agent/api_calls.json')
    if len(calls) != receipt['api_calls'] or any(c['response'].get('model') != 'gpt-5.4-2026-03-05' for c in calls):
        raise ValueError('api_evidence_mismatch')
    if not (td / 'agent/trajectory.json').is_file():
        raise ValueError('trajectory_missing')
    metrics = normalize_metrics(result, receipt)
    return {'reward': reward, **metrics, 'actual_model': 'gpt-5.4-2026-03-05',
            'result_sha256': hashlib.sha256((td / 'result.json').read_bytes()).hexdigest(),
            'trace_sha256': hashlib.sha256((td / 'agent/trajectory.json').read_bytes()).hexdigest()}
