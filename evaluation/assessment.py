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


def api_token_usage(calls):
    """Sum recorded response usage; absent accounting is not a zero-token call."""
    totals = {'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0}
    for call in calls:
        response = call.get('response') if isinstance(call, dict) else None
        usage = response.get('usage') if isinstance(response, dict) else None
        if not isinstance(usage, dict):
            raise ValueError('api_usage_missing')
        inp = usage.get('prompt_tokens', usage.get('input_tokens'))
        out = usage.get('completion_tokens', usage.get('output_tokens'))
        if type(inp) is not int or inp <= 0 or type(out) is not int or out < 0:
            raise ValueError('api_usage_invalid_tokens')
        details = usage.get('prompt_tokens_details', usage.get('input_tokens_details'))
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise ValueError('api_usage_invalid_details')
        cached = details.get('cached_tokens', 0)
        if type(cached) is not int or not 0 <= cached <= inp:
            raise ValueError('api_usage_invalid_cached_tokens')
        totals['input_tokens'] += inp
        totals['output_tokens'] += out
        totals['cached_tokens'] += cached
    return totals


def assess_trial(trial_directory, method, binary=True, *, require_retrieval=None, runtime=None):
    """Original model/transport/score gates plus canonical report evidence.

    This function does not turn missing reports, setup failures or null rewards
    into valid zeros. Container cleanup is checked by the runner separately.
    """
    from goskills_eval.runtime import resolve_runtime
    runtime = resolve_runtime(runtime)
    td = Path(trial_directory)
    read = lambda path: json.loads(path.read_text())
    result = read(td / 'result.json')
    receipt = read(td / 'agent/agent_receipt.json')
    if receipt.get('method') != method:
        raise ValueError('agent_method_mismatch')
    if type(receipt.get('api_calls')) is not int or receipt['api_calls'] <= 0 or receipt.get('actual_models') != [runtime.expected_model] or receipt.get('transport_fatal'):
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
    if not isinstance(calls, list) or len(calls) != receipt['api_calls'] or any(
            not isinstance(c, dict) or not isinstance(c.get('response'), dict) or
            c['response'].get('model') != runtime.expected_model for c in calls):
        raise ValueError('api_evidence_mismatch')
    if not (td / 'agent/trajectory.json').is_file():
        raise ValueError('trajectory_missing')
    metrics = normalize_metrics(result, receipt)
    recorded_usage = api_token_usage(calls)
    if any(metrics[key] != value for key, value in recorded_usage.items() if key in metrics):
        raise ValueError('api_usage_totals_mismatch')
    return {'reward': reward, **metrics, 'actual_model': runtime.expected_model,
            'result_sha256': hashlib.sha256((td / 'result.json').read_bytes()).hexdigest(),
            'trace_sha256': hashlib.sha256((td / 'agent/trajectory.json').read_bytes()).hexdigest()}
