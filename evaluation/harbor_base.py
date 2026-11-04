"""Pure OpenAI-compatible Direct API Harbor agent with bash tool execution.

This agent intentionally does not install or call Codex CLI. The controller runs
on the host, calls the configured OpenAI-compatible `/chat/completions` endpoint,
and executes returned bash tool calls inside the benchmark container.
"""

from __future__ import annotations

import json
import hashlib
import os
import shlex
import time
from goskills_eval.async_http import chat_completion
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harbor.agents.installed.base import BaseInstalledAgent, CliFlag, with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.agent.name import AgentName
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)


def redact_secret(value: Any) -> Any:
    """Redact inherited credentials at the observation/persistence boundary."""
    secrets = sorted({v for k, v in os.environ.items() if v and (k.endswith("_KEY") or k.endswith("_TOKEN") or k in {"API_KEY", "API_TOKEN"})}, key=len, reverse=True)
    def walk(item: Any) -> Any:
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[REDACTED]")
            return item
        if isinstance(item, dict):
            return {walk(k): walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        if isinstance(item, tuple):
            return tuple(walk(v) for v in item)
        return item
    return walk(value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 120)].rstrip() + "\n... [output truncated]"


def load_api_key(env_key: str) -> str:
    candidates = [env_key, "OPENAI_API_KEY", "DIRECT_API_KEY", "API_KEY", "GOS_LLM_OPENAI_API_KEY"]
    for key in candidates:
        value = os.environ.get(key)
        if value and not value.startswith(("your-", "optional-")):
            return value
    raise RuntimeError(f"Missing API key. Set {env_key} or OPENAI_API_KEY.")


class DirectAPIBashAgent(BaseInstalledAgent):
    """A minimal tool-using coding agent backed by direct HTTP API calls."""

    SUPPORTS_ATIF: bool = True

    CLI_FLAGS = [
        CliFlag("base_url", cli="", type="str", env_fallback="OPENAI_BASE_URL"),
        CliFlag("api_env_key", cli="", type="str", default="OPENAI_API_KEY"),
        CliFlag("reasoning_effort", cli="", type="str", default="low"),
        CliFlag("max_turns", cli="", type="int", default=60),
        CliFlag("tool_timeout_sec", cli="", type="int", default=180),
        CliFlag("max_observation_chars", cli="", type="int", default=12000),
        CliFlag("max_completion_tokens", cli="", type="int", default=4096),
        CliFlag("request_audit_root", cli="", type="str", default=""),
    ]

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_tokens = 0
        self._reasoning_output_tokens = 0
        self._steps: list[Step] = []
        self._session_id = str(uuid.uuid4())
        self._api_calls: list[dict[str, Any]] = []
        self._turn_count = 0
        self._tool_call_count = 0

    @staticmethod
    def name() -> str:
        return "direct-api-bash"

    def version(self) -> str | None:
        return "cr-native-0.2.0-async-candidate"

    async def install(self, environment: BaseEnvironment) -> None:
        await self.exec_as_root(
            environment,
            command=(
                "if command -v bash >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then "
                "  mkdir -p /logs/agent; "
                "else "
                "  echo 'bash and python3 are required for direct-api-bash' >&2; exit 1; "
                "fi"
            ),
        )

    def populate_context_post_run(self, context: AgentContext) -> None:
        context.n_input_tokens = self._input_tokens
        context.n_output_tokens = self._output_tokens
        context.n_cache_tokens = self._cache_tokens
        context.metadata = {
            "agent": self.name(),
            "model": self.model_name,
            "total_tokens": self._input_tokens + self._output_tokens,
            "reasoning_output_tokens": self._reasoning_output_tokens,
            "agent_turns": self._turn_count,
            "tool_calls": self._tool_call_count,
            "finish_status": getattr(self, "_finish_status", "unknown"),
        }

    @property
    def _base_url(self) -> str:
        value = self._resolved_flags.get("base_url") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")
        if not value:
            value = "https://api.openai.com/v1"
        return str(value).rstrip("/")

    @property
    def _api_env_key(self) -> str:
        return str(self._resolved_flags.get("api_env_key") or "OPENAI_API_KEY")

    @property
    def _reasoning_effort(self) -> str:
        return str(self._resolved_flags.get("reasoning_effort") or "low")

    @property
    def _max_turns(self) -> int:
        return int(self._resolved_flags.get("max_turns") or 60)

    @property
    def _tool_timeout_sec(self) -> int:
        return int(self._resolved_flags.get("tool_timeout_sec") or 180)

    @property
    def _max_observation_chars(self) -> int:
        return int(self._resolved_flags.get("max_observation_chars") or 12000)

    @property
    def _max_completion_tokens(self) -> int:
        return int(self._resolved_flags.get("max_completion_tokens") or 4096)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {load_api_key(self._api_env_key)}",
            "Content-Type": "application/json",
        }

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a bash command inside the SkillBench task container.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The bash command to run.",
                            }
                        },
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

    def _request_payload(self, messages: list[dict[str, Any]], *, include_reasoning: bool, use_max_completion_tokens: bool) -> dict[str, Any]:
        if not self.model_name:
            raise RuntimeError("model_name is required")
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "tools": self._tools(),
            "tool_choice": "auto",
            "temperature": 0,
        }
        if use_max_completion_tokens:
            payload["max_completion_tokens"] = self._max_completion_tokens
        else:
            payload["max_tokens"] = self._max_completion_tokens
        if include_reasoning and self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        return payload

    async def _chat_completion(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        audit_root=self._resolved_flags.get("request_audit_root")
        if not audit_root:
            raise RuntimeError("Async candidate requires a public external request_audit_root")
        trial=Path(self.logs_dir).resolve().parent
        return await chat_completion(
            messages, endpoint=f"{self._base_url}/chat/completions", model=self.model_name,
            payload_factory=self._request_payload, headers_factory=self._headers,
            calls=self._api_calls, logs_dir=self.logs_dir, redact=redact_secret, utc_now=utc_now,
            audit_root=Path(str(audit_root)),trial_identity={
                "job_id":trial.parent.name,"trial_id":trial.name,
                "attempt_uuid":self._request_attempt_uuid,
                "trial_path_sha256":hashlib.sha256(str(trial).encode()).hexdigest()},
        )

    def _record_usage(self, response: dict[str, Any]) -> Metrics | None:
        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
        cache_tokens = int(prompt_details.get("cached_tokens") or 0)
        reasoning_tokens = int(completion_details.get("reasoning_tokens") or 0)
        self._input_tokens += prompt_tokens
        self._output_tokens += completion_tokens
        self._cache_tokens += cache_tokens
        self._reasoning_output_tokens += reasoning_tokens
        if prompt_tokens == 0 and completion_tokens == 0:
            return None
        extra: dict[str, Any] = {}
        if prompt_details:
            extra["prompt_tokens_details"] = prompt_details
        if completion_details:
            extra["completion_tokens_details"] = completion_details
        return Metrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cache_tokens if cache_tokens else None,
            extra=extra if extra else None,
        )

    async def _run_bash(self, environment: BaseEnvironment, command: str) -> str:
        result = await environment.exec(
            command=f"set -o pipefail; {command}",
            timeout_sec=self._tool_timeout_sec,
        )
        output = [
            f"$ {command}",
            f"exit_code={result.return_code}",
        ]
        if result.stdout:
            output.append("stdout:")
            output.append(result.stdout)
        if result.stderr:
            output.append("stderr:")
            output.append(result.stderr)
        return clip(redact_secret("\n".join(output)), self._max_observation_chars)

    def _append_user_step(self, message: str) -> None:
        self._steps.append(
            Step(step_id=len(self._steps) + 1, timestamp=utc_now(), source="user", message=message)
        )

    def _append_agent_step(
        self,
        message: str,
        *,
        tool_calls: list[ToolCall] | None,
        observation: Observation | None,
        metrics: Metrics | None,
    ) -> None:
        self._steps.append(
            Step(
                step_id=len(self._steps) + 1,
                timestamp=utc_now(),
                source="agent",
                model_name=self.model_name,
                reasoning_effort=self._reasoning_effort,
                message=message or "",
                tool_calls=tool_calls,
                observation=observation,
                metrics=metrics,
            )
        )

    async def _save_trajectory(self, environment: BaseEnvironment) -> None:
        trajectory = Trajectory(
            session_id=self._session_id,
            agent=Agent(
                name=self.name(),
                version=self.version() or "unknown",
                model_name=self.model_name,
                tool_definitions=self._tools(),
                extra={"base_url": self._base_url},
            ),
            steps=self._steps
            or [Step(step_id=1, timestamp=utc_now(), source="user", message="No interaction recorded.")],
            final_metrics=FinalMetrics(
                total_prompt_tokens=self._input_tokens,
                total_completion_tokens=self._output_tokens,
                total_cached_tokens=self._cache_tokens if self._cache_tokens else None,
                total_steps=len(self._steps),
                extra={
                    "total_tokens": self._input_tokens + self._output_tokens,
                    "reasoning_output_tokens": self._reasoning_output_tokens,
            "agent_turns": self._turn_count,
                    "tool_calls": self._tool_call_count,
                    "finish_status": getattr(self, "_finish_status", "unknown"),
                },
            ),
            notes="Generated by pure direct-api-bash Harbor agent.",
        )
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        trajectory_dict = redact_secret(trajectory.to_json_dict())
        (self.logs_dir / "trajectory.json").write_text(
            json.dumps(trajectory_dict, indent=2),
            encoding="utf-8",
        )
        escaped = repr(json.dumps(trajectory_dict, ensure_ascii=False))
        await environment.exec(
            command=f"mkdir -p /logs/agent && python3 - <<'PY'\nimport json\nfrom pathlib import Path\nPath('/logs/agent/trajectory.json').write_text({escaped})\nPY"
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        self._request_attempt_uuid=str(uuid.uuid4())
        system = (
            "You are a direct-API autonomous coding agent inside a SkillBench task. "
            "Use the bash tool to inspect files, follow the supplied skill-access condition, edit files, and verify outputs. "
            "Do not ask the user for clarification. Start by reading /root/AGENTS.md if it exists. "
            "Preserve required output paths exactly. Finish with a concise final answer only after the artifact is produced or no further useful action is possible."
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": instruction},
        ]
        self._append_user_step(instruction)

        final_text = ""
        try:
            for _turn in range(self._max_turns):
                self._turn_count += 1
                response = await self._chat_completion(messages)
                metrics = self._record_usage(response)
                choices = response.get("choices") or []
                if not choices:
                    raise RuntimeError(f"Direct API response missing choices: {response}")
                message = choices[0].get("message") or {}
                content = message.get("content") or ""
                tool_calls_raw = message.get("tool_calls") or []
                self._tool_call_count += len(tool_calls_raw)
                messages.append(message)

                tool_calls: list[ToolCall] = []
                observation_results: list[ObservationResult] = []
                for raw_call in tool_calls_raw:
                    call_id = str(raw_call.get("id") or f"call_{uuid.uuid4().hex[:8]}")
                    function = raw_call.get("function") or {}
                    name = function.get("name") or "bash"
                    raw_arguments = function.get("arguments") or "{}"
                    try:
                        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
                    except Exception:
                        arguments = {"command": str(raw_arguments)}
                    command = str(arguments.get("command") or "")
                    if name != "bash" or not command:
                        observation = f"Unsupported tool call {name}; expected bash(command)."
                    else:
                        observation = await self._run_bash(environment, command)
                    tool_calls.append(ToolCall(tool_call_id=call_id, function_name=name, arguments=arguments))
                    observation_results.append(ObservationResult(source_call_id=call_id, content=observation))
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": observation})

                observation_obj = Observation(results=observation_results) if observation_results else None
                self._append_agent_step(
                    content,
                    tool_calls=tool_calls or None,
                    observation=observation_obj,
                    metrics=metrics,
                )
                if not tool_calls_raw:
                    final_text = str(content)
                    self._finish_status = "completed"
                    break
            else:
                final_text = "Reached max_turns."
                self._finish_status = "max_turns"
                raise RuntimeError("Agent reached max_turns without a final answer")

            if final_text:
                safe_text = shlex.quote(redact_secret(final_text))
                await environment.exec(command=f"mkdir -p /logs/agent && printf '%s\\n' {safe_text} > /logs/agent/final.txt")
        finally:
            # A parsed response can arrive just before cancellation during client
            # cleanup. Reconcile every persisted success exactly once for billing;
            # it is never converted to an extra model turn or bash execution.
            self._input_tokens = self._output_tokens = self._cache_tokens = self._reasoning_output_tokens = 0
            for call in self._api_calls:
                self._record_usage(call["response"])
            self.populate_context_post_run(context)
            await self._save_trajectory(environment)
