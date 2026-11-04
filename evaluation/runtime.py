"""One model configuration contract for all benchmark entrypoints.

The gpt54 profile is the recorded reproduction setting. Custom models must be
selected explicitly and support the OpenAI-compatible chat/tool interface.
Task and method settings remain independent of model selection.
"""
from dataclasses import asdict, dataclass
from importlib.resources import files
import json

METHODS = ('noskills', 'vanilla', 'vector', 'native-gos', 'goskills-d')

TERMINAL_SETTINGS = dict(max_turns=60, max_completion_tokens=4096,
                         tool_timeout_sec=180, max_observation_chars=12000)
ALFWORLD_SETTINGS = dict(max_steps=30, seed=42, max_completion_tokens=4096)


@dataclass(frozen=True)
class RuntimeConfig:
    profile: str
    model: str
    expected_model: str
    reasoning_effort: str | None
    completion_token_field: str

    def __post_init__(self):
        if not isinstance(self.profile, str) or self.profile not in {'gpt54', 'custom'}:
            raise ValueError('Unknown runtime profile')
        for value in (self.model, self.expected_model):
            if not isinstance(value, str) or not value or value.strip() != value or any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError('Model identities must be nonempty strings without whitespace')
        if self.reasoning_effort is not None and (not isinstance(self.reasoning_effort, str) or self.reasoning_effort not in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}):
            raise ValueError('Unsupported reasoning effort')
        if not isinstance(self.completion_token_field, str) or self.completion_token_field not in {'max_completion_tokens', 'max_tokens'}:
            raise ValueError('Unsupported completion token field')
        if self.profile == 'gpt54' and self.to_dict() != pinned_config():
            raise ValueError('The gpt54 reproduction profile cannot be overridden; select custom')

    def to_dict(self):
        return asdict(self)

    def agent_kwargs(self):
        return {**TERMINAL_SETTINGS, 'reasoning_effort': self.reasoning_effort or '',
                'expected_model': self.expected_model,
                'completion_token_field': self.completion_token_field}

    def validate_response(self, actual_model):
        if actual_model != self.expected_model:
            raise ValueError('actual_model_mismatch')


def pinned_config():
    return json.loads(files('goskills_eval.experiments.configs').joinpath('gpt54.json').read_text())


def resolve_runtime(value=None):
    if isinstance(value, RuntimeConfig):
        return value
    if value is None:
        value = pinned_config()
    if not isinstance(value, dict) or set(value) != set(RuntimeConfig.__dataclass_fields__):
        raise ValueError('Runtime configuration requires exactly profile/model/expected_model/reasoning_effort/completion_token_field')
    return RuntimeConfig(**value)


def add_runtime_arguments(parser):
    parser.add_argument('--profile', choices=['gpt54', 'custom'], default='gpt54',
                        help='Pinned GPT-5.4 reproduction settings, or explicit custom chat model')
    parser.add_argument('--model', help='Requested model ID (custom profile only)')
    parser.add_argument('--expected-model', help='Exact response model ID; defaults to --model for custom')
    parser.add_argument('--reasoning-effort', choices=['omit', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh'],
                        help='Custom profile only; default omits the reasoning parameter')
    parser.add_argument('--completion-token-field', choices=['max_completion_tokens', 'max_tokens'],
                        help='Custom profile only; default max_completion_tokens')


def runtime_from_args(args):
    if args.profile == 'gpt54':
        if any(getattr(args, name) is not None for name in ('model', 'expected_model', 'reasoning_effort', 'completion_token_field')):
            raise ValueError('Use --profile custom to override model parameters')
        return resolve_runtime()
    return resolve_runtime(dict(profile='custom', model=args.model,
        expected_model=args.expected_model or args.model,
        reasoning_effort=None if args.reasoning_effort in (None, 'omit') else args.reasoning_effort,
        completion_token_field=args.completion_token_field or 'max_completion_tokens'))


def runtime_cli(config):
    config = resolve_runtime(config)
    if config.profile == 'gpt54':
        return ['--profile', 'gpt54']
    return ['--profile', 'custom', '--model', config.model, '--expected-model', config.expected_model,
            '--reasoning-effort', config.reasoning_effort or 'omit',
            '--completion-token-field', config.completion_token_field]
