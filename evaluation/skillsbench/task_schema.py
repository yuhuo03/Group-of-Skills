"""Inspect SkillsBench layouts without modifying the source task.

Only explicitly supported task.md fields are converted. In particular, a new
verifier policy must never be silently dropped to make a task run on Harbor.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
try:
    import tomllib
except ImportError:
    import tomli as tomllib

# Single-step Linux task fields supported by the pinned Harbor 0.20 runtime.
# Complex verifier services/hardening and multi-step tasks need their own runner.
FIELDS = {
    'agent': {'timeout_sec', 'user', 'network_mode', 'allowed_hosts'},
    'verifier': {'timeout_sec', 'env', 'user', 'network_mode', 'allowed_hosts'},
    'environment': {'build_timeout_sec', 'docker_image', 'os', 'cpus',
                    'memory_mb', 'storage_mb', 'gpus', 'gpu_types', 'env',
                    'workdir', 'allow_internet', 'network_mode', 'allowed_hosts'},
    'solution': {'env'},
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def files(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


def _yaml(content):
    try:
        import yaml
    except ImportError:
        raise ValueError('task.md requires PyYAML; install the terminal extra') from None

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        result = {}
        for key, value in node.value:
            name = loader.construct_object(key, deep=deep)
            if not isinstance(name, str) or name in result:
                raise ValueError('Task YAML keys must be unique strings')
            result[name] = loader.construct_object(value, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        return yaml.load(content, Loader=UniqueLoader)
    except yaml.YAMLError:
        raise ValueError('Invalid task.md YAML front matter') from None


def _toml_value(value):
    # Inline tables retain nested metadata/env maps and dotted keys literally.
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if type(value) is bool:
        return str(value).lower()
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return repr(value)
    if isinstance(value, list):
        return '[' + ', '.join(_toml_value(x) for x in value) + ']'
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return '{' + ', '.join(json.dumps(k) + ' = ' + _toml_value(v)
                              for k, v in value.items()) + '}'
    raise ValueError('Task YAML contains a value that cannot be preserved in TOML')


def _modern(task):
    content = (task / 'task.md').read_text(encoding='utf-8')
    match = re.fullmatch(r'---[^\S\n]*\n(.*?)\n---[^\S\n]*\n(.*)', content, re.S)
    if not match:
        raise ValueError('task.md requires YAML front matter and instruction body')
    config = _yaml(match[1])
    if not isinstance(config, dict) or config.get('schema_version') != '1.3':
        raise ValueError('Supported task.md schema_version is the string 1.3')
    unknown = set(config) - {'schema_version', 'metadata', 'sandbox', *FIELDS}
    if unknown:
        raise ValueError('Unsupported task.md fields: ' + ', '.join(sorted(unknown)))
    if 'sandbox' in config:
        if 'environment' in config:
            raise ValueError('task.md cannot specify both sandbox and environment')
        config['environment'] = config.pop('sandbox')
    for section, allowed in FIELDS.items():
        values = config.get(section, {})
        if not isinstance(values, dict):
            raise ValueError('Task section must be a mapping: ' + section)
        # These describe Harbor's ordinary test script in the main container.
        # Other services and hardening are not equivalent to that execution.
        if section == 'verifier':
            if 'type' in values and values.pop('type') != 'test-script':
                raise ValueError('Unsupported verifier.type; expected test-script')
            if 'service' in values and values.pop('service') != 'main':
                raise ValueError('Non-main verifier.service needs an explicit runner')
        unknown = set(values) - allowed
        if unknown:
            raise ValueError('Unsupported ' + section + ' fields: ' + ', '.join(sorted(unknown)))
        if 'network_mode' in values:
            # SkillsBench calls the no-network policy "none". Harbor calls it
            # "no-network"; never widen allowlist/unknown policies to public.
            mode = values['network_mode']
            if mode == 'none':
                values['network_mode'] = mode = 'no-network'
            if mode not in {'no-network', 'public', 'allowlist'}:
                raise ValueError('Unsupported task network_mode')
            if 'allow_internet' in values:
                raise ValueError('Specify network_mode or allow_internet, not both')
        if 'allowed_hosts' in values and values.get('network_mode') != 'allowlist':
            raise ValueError('allowed_hosts requires network_mode=allowlist')
        if 'env' in values and (not isinstance(values['env'], dict) or
                               any(not isinstance(v, str) for v in values['env'].values())):
            raise ValueError('Task env values must be strings')
    if not isinstance(config.get('metadata', {}), dict):
        raise ValueError('Task metadata must be a mapping')
    instruction = match[2].lstrip('\n')
    if not instruction.strip():
        raise ValueError('Empty task instruction')
    rendered = '\n'.join(json.dumps(k) + ' = ' + _toml_value(v)
                         for k, v in config.items()) + '\n'
    if tomllib.loads(rendered) != config:
        raise ValueError('Task conversion changed configuration values')
    return config, {'task.toml': rendered, 'instruction.md': instruction}


def inspect_task(task):
    """Return a read-only normalization plan used by doctor, campaign and runner."""
    task = Path(task)
    if any(p.is_symlink() for p in task.rglob('*')):
        raise ValueError('Task symlinks must be materialized before preparation')
    native = (task / 'task.toml').is_file()
    modern = (task / 'task.md').is_file()
    if native and modern:
        raise ValueError('Ambiguous task: both task.toml and task.md are present')
    generated = {}
    copies = {}
    if native:
        config = tomllib.loads((task / 'task.toml').read_text(encoding='utf-8'))
        if not (task / 'instruction.md').is_file():
            raise ValueError('Missing SkillsBench task file: instruction.md')
        protected = ['task.toml', 'instruction.md']
    elif modern:
        config, generated = _modern(task)
        protected = ['task.md']
        for name, text in generated.items():
            if (task / name).exists() and (task / name).read_bytes() != text.encode():
                raise ValueError('Task normalization would overwrite ' + name)
        for source, destination in [('verifier', 'tests'), ('oracle', 'solution')]:
            src, dst = task / source, task / destination
            if src.exists():
                if not src.is_dir() or (dst.exists() and not dst.is_dir()):
                    raise ValueError('Task verifier/oracle paths must be directories')
                if dst.exists() and files(src) != files(dst):
                    raise ValueError('Conflicting task directories: ' + source + '/' + destination)
                copies[source] = destination
        if not (task / 'verifier/test.sh').is_file() and not (task / 'tests/test.sh').is_file():
            raise ValueError('Missing SkillsBench test.sh verifier')
    else:
        raise ValueError('Missing SkillsBench task.toml or task.md')
    for folder in ('tests', 'verifier', 'solution', 'oracle'):
        protected += [p.relative_to(task).as_posix()
                      for p in sorted((task / folder).rglob('*')) if p.is_file()]
    return {'layout': 'task.toml' if native else 'task.md', 'config': config,
            'generated': generated, 'copies': copies,
            'protected': {name: digest((task / name).read_bytes()) for name in protected}}


def normalize_copy(task, plan):
    """Apply a checked plan to a fresh copy, preserving all original source files."""
    task = Path(task)
    for name, expected in plan['protected'].items():
        if digest((task / name).read_bytes()) != expected:
            raise ValueError('Protected task file changed: ' + name)
    for name, text in plan['generated'].items():
        path = task / name
        if path.exists():
            if path.read_bytes() != text.encode():
                raise ValueError('Task normalization would overwrite ' + name)
        else:
            with path.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(text)
    for source, destination in plan['copies'].items():
        if not (task / destination).exists():
            shutil.copytree(task / source, task / destination)
        if files(task / source) != files(task / destination):
            raise ValueError('Task directory conversion changed source bytes')
