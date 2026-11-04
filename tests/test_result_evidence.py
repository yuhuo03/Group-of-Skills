"""Receipt accounting must agree with actual per-call API usage."""
import json
import pytest
from goskills_eval.assessment import assess_trial


def evidence(root, usage):
    (root/'agent').mkdir(); (root/'verifier').mkdir()
    records = {
        'result.json': {'agent_runtime_seconds': 2, 'verifier_result': {'rewards': {'reward': 0}}},
        'agent/agent_receipt.json': {'method': 'noskills', 'api_calls': 1,
            'actual_models': ['gpt-5.4-2026-03-05'], 'finish_status': 'completed',
            'transport_fatal': False, 'token_usage': {'input': 10, 'output': 2, 'cached': 3}},
        'agent/api_calls.json': [{'response': {'model': 'gpt-5.4-2026-03-05', 'usage': usage}}],
        'agent/trajectory.json': {},
        'verifier/ctrf.json': {'results': {'tests': [{'status': 'failed'}], 'summary': {'tests': 1}}},
    }
    for name, value in records.items(): (root/name).write_text(json.dumps(value))


@pytest.mark.parametrize('usage', [None, {}, {'prompt_tokens': 10},
    {'prompt_tokens': True, 'completion_tokens': 2},
    {'prompt_tokens': 10.5, 'completion_tokens': 2},
    {'prompt_tokens': 0, 'completion_tokens': 2},
    {'prompt_tokens': 10, 'completion_tokens': -1},
    {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 11}}])
def test_missing_or_invalid_api_usage_is_not_a_valid_zero(tmp_path, usage):
    evidence(tmp_path, usage)
    with pytest.raises(ValueError): assess_trial(tmp_path, 'noskills')


def test_receipt_totals_must_match_api_calls(tmp_path):
    evidence(tmp_path, {'prompt_tokens': 11, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 3}})
    with pytest.raises(ValueError, match='usage'): assess_trial(tmp_path, 'noskills')


def test_valid_zero_and_exact_token_counts_are_preserved(tmp_path):
    evidence(tmp_path, {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 3}})
    checked = assess_trial(tmp_path, 'noskills')
    assert (checked['reward'], checked['input_tokens'], checked['output_tokens'], checked['cached_tokens']) == (0, 10, 2, 3)


def test_multiple_responses_and_usage_aliases(tmp_path):
    evidence(tmp_path, {'prompt_tokens': 4, 'completion_tokens': 0})
    calls_path=tmp_path/'agent/api_calls.json'
    calls=json.loads(calls_path.read_text())
    calls.append({'response': {'model': 'gpt-5.4-2026-03-05', 'usage': {
        'input_tokens': 6, 'output_tokens': 2, 'input_tokens_details': {'cached_tokens': 3}}}})
    calls_path.write_text(json.dumps(calls))
    receipt_path=tmp_path/'agent/agent_receipt.json'
    receipt=json.loads(receipt_path.read_text());receipt['api_calls']=2
    receipt_path.write_text(json.dumps(receipt))
    assert assess_trial(tmp_path, 'noskills')['input_tokens']==10
