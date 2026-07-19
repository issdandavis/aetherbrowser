"""Provider-backed execution for AetherBrowser command plans."""

from __future__ import annotations

import asyncio
from importlib.util import find_spec
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

from src.aetherbrowser.command_planner import CommandPlan
from src.aetherbrowser.router import ModelProvider, PROVIDER_ENV_VARS, PROVIDER_FAMILY

ProviderAdapter = Callable[[str, str], Awaitable[str]]


@dataclass
class ProviderExecutionResult:
    provider: str
    model_id: str
    text: str
    attempted: list[str]
    fallback_used: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "text": self.text,
            "attempted": self.attempted,
            "fallback_used": self.fallback_used,
        }


@dataclass
class ProviderRuntimeStatus:
    provider: ModelProvider
    family: str
    model_id: str
    available: bool
    reason: str
    env_vars: tuple[str, ...]
    packages: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "model_id": self.model_id,
            "available": self.available,
            "reason": self.reason,
            "env_vars": list(self.env_vars),
            "packages": list(self.packages),
        }


_MODEL_ID_DEFAULTS: dict[ModelProvider, tuple[str, str]] = {
    ModelProvider.LOCAL: ("AETHERBROWSER_MODEL_LOCAL", "local-control"),
    ModelProvider.OLLAMA: ("AETHERBROWSER_MODEL_OLLAMA", "qwen2.5-coder:1.5b"),
    ModelProvider.HAIKU: ("AETHERBROWSER_MODEL_HAIKU", "claude-3-5-haiku-20241022"),
    ModelProvider.SONNET: ("AETHERBROWSER_MODEL_SONNET", "claude-sonnet-4-20250514"),
    ModelProvider.OPUS: ("AETHERBROWSER_MODEL_OPUS", "claude-opus-4-1-20250805"),
    ModelProvider.FLASH: ("AETHERBROWSER_MODEL_FLASH", "gpt-4o-mini"),
    ModelProvider.GROK: ("AETHERBROWSER_MODEL_GROK", "grok-3-mini"),
    ModelProvider.HUGGINGFACE: (
        "AETHERBROWSER_MODEL_HUGGINGFACE",
        "mistralai/Mistral-7B-Instruct-v0.3",
    ),
    ModelProvider.GITHUB: ("AETHERBROWSER_MODEL_GITHUB", "openai/gpt-4o-mini"),
}


def _resolve_model_ids() -> dict[ModelProvider, str]:
    """Resolve model IDs at call time so env vars set after import are picked up."""
    return {provider: os.environ.get(env_var, default) for provider, (env_var, default) in _MODEL_ID_DEFAULTS.items()}


PROVIDER_PACKAGES: dict[ModelProvider, tuple[str, ...]] = {
    ModelProvider.LOCAL: (),
    # Ollama needs no third-party package: it uses httpx when present and falls
    # back to the stdlib urllib client, so it is always considered available.
    ModelProvider.OLLAMA: (),
    ModelProvider.HAIKU: ("anthropic",),
    ModelProvider.SONNET: ("anthropic",),
    ModelProvider.OPUS: ("anthropic",),
    ModelProvider.FLASH: ("openai",),
    ModelProvider.GROK: ("openai",),
    ModelProvider.HUGGINGFACE: ("huggingface_hub",),
    ModelProvider.GITHUB: ("openai",),  # OpenAI-compatible endpoint at models.github.ai
}

SYSTEM_PROMPT = (
    "You are AetherBrowser's execution brain operating under SCBE governance. "
    "Be concise, factual, and action-oriented. When a task is risky, acknowledge the gate. "
    "When a browser action is required, describe the next concrete step."
)


class ProviderExecutor:
    def __init__(
        self,
        *,
        adapters: dict[ModelProvider, ProviderAdapter] | None = None,
        model_ids: dict[ModelProvider, str] | None = None,
    ) -> None:
        self._model_id_overrides = dict(model_ids or {})
        self._adapters: dict[ModelProvider, ProviderAdapter] = {
            ModelProvider.LOCAL: self._call_local,
            ModelProvider.OLLAMA: self._call_ollama,
            ModelProvider.HAIKU: self._call_anthropic,
            ModelProvider.SONNET: self._call_anthropic,
            ModelProvider.OPUS: self._call_anthropic,
            ModelProvider.FLASH: self._call_openai,
            ModelProvider.GROK: self._call_xai,
            ModelProvider.HUGGINGFACE: self._call_huggingface,
            ModelProvider.GITHUB: self._call_github,
        }
        if adapters:
            self._adapters.update(adapters)

    @property
    def _model_ids(self) -> dict[ModelProvider, str]:
        return {**_resolve_model_ids(), **self._model_id_overrides}

    def runtime_status(self) -> dict[ModelProvider, ProviderRuntimeStatus]:
        return {provider: self._provider_runtime_status(provider) for provider in ModelProvider}

    def runtime_status_snapshot(self) -> dict[str, dict[str, object]]:
        return {provider.value: status.to_dict() for provider, status in self.runtime_status().items()}

    async def execute(
        self,
        plan: CommandPlan,
        *,
        context_summary: str = "",
    ) -> ProviderExecutionResult:
        prompt = self._build_prompt(plan, context_summary=context_summary)
        candidates = self._candidate_chain(plan)
        attempted: list[str] = []
        last_error: Exception | None = None

        for provider in candidates:
            model_id = self._model_ids[provider]
            attempted.append(provider.value)
            try:
                text = await self._adapters[provider](model_id, prompt)
                return ProviderExecutionResult(
                    provider=provider.value,
                    model_id=model_id,
                    text=text.strip(),
                    attempted=attempted,
                    fallback_used=len(attempted) > 1,
                )
            except Exception as exc:
                last_error = exc
                if not plan.auto_cascade:
                    break

        raise RuntimeError(
            f"Provider execution failed after attempting {', '.join(attempted)}: {last_error}"
        ) from last_error

    def _candidate_chain(self, plan: CommandPlan) -> list[ModelProvider]:
        chain: list[ModelProvider] = []
        for raw_provider in [plan.provider, *plan.fallback_chain]:
            provider = ModelProvider(raw_provider)
            if provider not in chain:
                chain.append(provider)
            if not plan.auto_cascade:
                break
        return chain

    def _provider_runtime_status(self, provider: ModelProvider) -> ProviderRuntimeStatus:
        env_vars = PROVIDER_ENV_VARS[provider]
        packages = PROVIDER_PACKAGES[provider]

        if not env_vars:
            return ProviderRuntimeStatus(
                provider=provider,
                family=PROVIDER_FAMILY[provider],
                model_id=self._model_ids[provider],
                available=True,
                reason="local_runtime",
                env_vars=env_vars,
                packages=packages,
            )

        if not any(os.environ.get(name, "").strip() for name in env_vars):
            return ProviderRuntimeStatus(
                provider=provider,
                family=PROVIDER_FAMILY[provider],
                model_id=self._model_ids[provider],
                available=False,
                reason=f"missing_env:{','.join(env_vars)}",
                env_vars=env_vars,
                packages=packages,
            )

        missing_packages = [name for name in packages if find_spec(name) is None]
        if missing_packages:
            return ProviderRuntimeStatus(
                provider=provider,
                family=PROVIDER_FAMILY[provider],
                model_id=self._model_ids[provider],
                available=False,
                reason=f"missing_package:{','.join(missing_packages)}",
                env_vars=env_vars,
                packages=packages,
            )

        return ProviderRuntimeStatus(
            provider=provider,
            family=PROVIDER_FAMILY[provider],
            model_id=self._model_ids[provider],
            available=True,
            reason="ready",
            env_vars=env_vars,
            packages=packages,
        )

    def _build_prompt(self, plan: CommandPlan, *, context_summary: str = "") -> str:
        assignment_lines = []
        for assignment in plan.assignments[:6]:
            role = assignment["role"].value if hasattr(assignment["role"], "value") else assignment["role"]
            assignment_lines.append(f"- {role}: {assignment['task']}")

        next_actions = [action.label for action in plan.next_actions[:3]]
        prompt_parts: list[str] = []
        # Prepend the shared-context block so every agent answers WITH the pooled
        # awareness (other tabs' intent, the current page, recent findings/log).
        if context_summary.strip():
            prompt_parts.extend([context_summary.strip(), ""])

        # Lead with the user's ACTUAL request -- it must dominate the prompt, or a
        # small model answers the orchestration framing instead of the question.
        prompt_parts.append(f"User request: {plan.text}")
        prompt_parts.append("")

        # Plan metadata is secondary awareness, NOT the task. Keep it compact so it
        # never overrides the request.
        meta = (f"(task={plan.task_type}, intent={plan.intent}, "
                f"complexity={plan.complexity.value}, risk={plan.risk_tier}, "
                f"browser_action={plan.browser_action_required})")
        prompt_parts.append("Plan context (for your awareness; do not just restate it): " + meta)
        if assignment_lines:
            prompt_parts.append("Assignments: " + "; ".join(a.lstrip("- ") for a in assignment_lines))

        # Final instruction: ANSWER the request. Only steer to a next step when a
        # browser action is actually required.
        if plan.browser_action_required:
            if next_actions:
                prompt_parts.append("Possible next steps: " + "; ".join(next_actions))
            prompt_parts.append(
                "Answer the user's request directly. If a browser action is needed, "
                "state the single concrete next step.")
        else:
            prompt_parts.append("Answer the user's request directly and concisely.")
        return "\n".join(prompt_parts)

    async def _call_local(self, model_id: str, prompt: str) -> str:
        del model_id
        lines = prompt.splitlines()
        request_line = next(
            (line for line in lines if line.startswith("User request: ")),
            "User request: ",
        )
        task_line = next(
            (line for line in lines if line.startswith("Task type: ")),
            "Task type: default",
        )
        risk_line = next((line for line in lines if line.startswith("Risk tier: ")), "Risk tier: low")
        browser_line = next(
            (line for line in lines if line.startswith("Browser action required: ")),
            "Browser action required: False",
        )
        action_lines = [line[2:] for line in lines if line.startswith("- ")]
        first_action = action_lines[0] if action_lines else "Begin with KO orchestration."
        return (
            f"Local execution lane active. {request_line.replace('User request: ', '')} "
            f"({task_line.replace('Task type: ', '')}, {risk_line.replace('Risk tier: ', '')}). "
            f"{browser_line.replace('Browser action required: ', 'Browser action required=')}. "
            f"Next: {first_action}"
        )

    async def _call_ollama(self, model_id: str, prompt: str) -> str:
        """Call the local Ollama server — real LLM, no API key, $0 cost.

        POSTs the SYSTEM_PROMPT + user prompt (which already carries the shared
        context_pool summary, prepended in `_build_prompt`) to the native
        ``/api/chat`` endpoint. Uses ``httpx.AsyncClient`` when available and
        otherwise drops to the stdlib ``urllib`` client run off the event loop.
        """
        base_url = os.environ.get("AETHERBROWSER_OLLAMA_URL", "http://localhost:11434").rstrip("/")
        endpoint = f"{base_url}/api/chat"
        payload = {
            "model": model_id,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 700},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }

        if find_spec("httpx") is not None:
            import httpx  # type: ignore[import-untyped]

            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(endpoint, json=payload)
                    response.raise_for_status()
                    data = response.json()
            except Exception as exc:  # pragma: no cover - depends on local server
                raise RuntimeError(f"Ollama request failed at {endpoint}: {exc}") from exc
        else:
            data = await asyncio.to_thread(self._ollama_request_urllib, endpoint, payload)

        text = ""
        if isinstance(data, dict):
            message = data.get("message")
            if isinstance(message, dict):
                text = message.get("content", "") or ""
            if not text:
                # Tolerate the /api/generate-style shape too.
                text = data.get("response", "") or ""
        if not text.strip():
            raise RuntimeError(f"Ollama returned no content from {endpoint}")
        return text

    @staticmethod
    def _ollama_request_urllib(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        import json
        import urllib.error
        import urllib.request

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120.0) as resp:  # noqa: S310 - local server
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:  # pragma: no cover - depends on local server
            raise RuntimeError(f"Ollama request failed at {endpoint}: {exc}") from exc
        return json.loads(raw)

    async def _call_anthropic(self, model_id: str, prompt: str) -> str:
        try:
            import anthropic  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError("anthropic package is not installed") from exc

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model_id,
            max_tokens=700,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if hasattr(block, "text"))

    async def _call_openai(self, model_id: str, prompt: str) -> str:
        try:
            import openai  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError("openai package is not installed") from exc

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model_id,
            temperature=0.2,
            max_tokens=700,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    async def _call_xai(self, model_id: str, prompt: str) -> str:
        try:
            import openai  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError("openai package is required for the xAI lane") from exc

        api_key = os.environ.get("XAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("XAI_API_KEY is not configured")

        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1"),
        )
        response = await client.chat.completions.create(
            model=model_id,
            temperature=0.2,
            max_tokens=700,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    async def _call_github(self, model_id: str, prompt: str) -> str:
        # Free frontier: GitHub Models exposes an OpenAI-compatible endpoint. A gh token
        # (GITHUB_TOKEN / GH_TOKEN, e.g. `gh auth token`) authenticates real gpt-4o/Llama-70B at $0.
        try:
            import openai  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError("openai package is required for the GitHub Models lane") from exc

        api_key = (os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")).strip()
        if not api_key:
            raise RuntimeError("GITHUB_TOKEN / GH_TOKEN is not configured")

        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=os.environ.get("GITHUB_MODELS_BASE_URL", "https://models.github.ai/inference"),
        )
        response = await client.chat.completions.create(
            model=model_id,
            temperature=0.2,
            max_tokens=700,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    async def _call_huggingface(self, model_id: str, prompt: str) -> str:
        try:
            from huggingface_hub import AsyncInferenceClient  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError("huggingface_hub package is not installed") from exc

        token = os.environ.get("HF_TOKEN", "").strip()
        if not token:
            raise RuntimeError("HF_TOKEN is not configured")

        client = AsyncInferenceClient(model=model_id, token=token)
        response = await client.text_generation(
            prompt=f"[INST] {SYSTEM_PROMPT}\n\n{prompt} [/INST]",
            max_new_tokens=700,
            temperature=0.2,
        )
        return response
