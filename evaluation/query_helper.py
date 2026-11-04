"""Isolated five-method retrieval. Stdout contains one structured result only."""
from goskills_eval.utils import Path, json, write, sha
import contextlib
import hashlib
import sys


def execute_query(data, backend=None):
    directory = Path(data['directory'])
    directory.mkdir(parents=True, exist_ok=False)
    try:
        method = data['method']
        if method not in ('noskills', 'vanilla', 'vector', 'native-gos', 'goskills-d'):
            raise ValueError('Unknown method')
        if not isinstance(data.get('query'), str):
            raise ValueError('Query must be a string')
        if backend is None:
            from goskills_eval.skill import query as backend
        resources = {key: data.get(key) for key in ('skills_root', 'pool', 'workspace', 'upstream')}
        with (directory / 'retrieval-private.log').open('x') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            content = backend(method, data['query'], directory, **resources,
                              source_root='/opt/graphskills/skills')
        if not isinstance(content, str):
            raise ValueError('Retrieval backend must return text')
        # Vanilla is intentionally the complete official catalog, not a top-k budget.
        if method in ('vector', 'native-gos', 'goskills-d') and len(content) > 9000:
            raise ValueError('context_budget_exceeded')
        receipt = {'status': 'PASSED', 'method': method,
                   'query_sha256': hashlib.sha256(data['query'].encode()).hexdigest(),
                   'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
                   'offline_fixture': False}
        for filename, key in [('bundle.json', 'bundle_sha256'), ('backend_receipt.json', 'backend_receipt_sha256')]:
            if (directory / filename).is_file():
                receipt[key] = sha(directory / filename)
        write(directory / 'receipt.json', receipt, True)
        return 0, {**receipt, 'content': content}
    except Exception as exc:
        receipt = {'status': 'FAILED', 'error_type': type(exc).__name__}
        write(directory / 'receipt.json', receipt, True)
        return 1, receipt


def main():
    code, result = execute_query(json.load(sys.stdin))
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
