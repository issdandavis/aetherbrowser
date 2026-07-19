"""
OctoArmor Model Router
=======================

Every model can play any role. Routing is a preference, not a lock.

1. Task arrives -> score complexity (LOW / MEDIUM / HIGH)
2. Pick cheapest model that can handle it
3. Assign tongue role based on task type
4. If rate-limited, cascade to next model
5. Sacred Tongue -> model mapping is configurable
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ModelProvider(str, Enum):
    OPUS = "opus"
    SONNET = "sonnet"
    HAIKU = "haiku"
    FLASH = "flash"
    GROK = "grok"
    # Local Ollama brain: real LLM, no API key, $0. Listed before LOCAL so it is
    # the preferred keyless lane and LOCAL stays the deterministic last resort.
    OLLAMA = "ollama"
    LOCAL = "local"
    HUGGINGFACE = "huggingface"
    GITHUB = "github"  # free frontier: gh token -> models.github.ai (gpt-4o/Llama-70B, $0, no card)


class TaskComplexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


MODEL_COST_TIER: dict[ModelProvider, int] = {
    ModelProvider.LOCAL: 0,
    ModelProvider.OLLAMA: 0,
    ModelProvider.HAIKU: 1,
    ModelProvider.FLASH: 1,
    ModelProvider.GROK: 2,
    ModelProvider.SONNET: 3,
    ModelProvider.OPUS: 4,
    ModelProvider.HUGGINGFACE: 1,
    ModelProvider.GITHUB: 1,  # free frontier -> cheap tier, usable for low/medium complexity
}

PROVIDER_ENV_VARS: dict[ModelProvider, tuple[str, ...]] = {
    ModelProvider.LOCAL: (),
    # Ollama is a local server: no API key required, so an empty env tuple makes
    # it count as available without any cloud credential.
    ModelProvider.OLLAMA: (),
    ModelProvider.HAIKU: ("ANTHROPIC_API_KEY",),
    ModelProvider.SONNET: ("ANTHROPIC_API_KEY",),
    ModelProvider.OPUS: ("ANTHROPIC_API_KEY",),
    ModelProvider.FLASH: ("OPENAI_API_KEY",),
    ModelProvider.GROK: ("XAI_API_KEY",),
    ModelProvider.HUGGINGFACE: ("HF_TOKEN",),
    ModelProvider.GITHUB: ("GITHUB_TOKEN", "GH_TOKEN"),  # available if a gh token is exported
}

PROVIDER_FAMILY: dict[ModelProvider, str] = {
    ModelProvider.LOCAL: "local",
    ModelProvider.OLLAMA: "ollama",
    ModelProvider.HAIKU: "anthropic",
    ModelProvider.SONNET: "anthropic",
    ModelProvider.OPUS: "anthropic",
    ModelProvider.FLASH: "openai",
    ModelProvider.GROK: "xai",
    ModelProvider.HUGGINGFACE: "huggingface",
    ModelProvider.GITHUB: "github",
}

COMPLEXITY_MIN_TIER: dict[TaskComplexity, int] = {
    TaskComplexity.LOW: 0,
    TaskComplexity.MEDIUM: 2,
    TaskComplexity.HIGH: 3,
}

DEFAULT_PREFERENCES: dict[str, ModelProvider] = {
    # KO (orchestrator) defaults to the local Ollama brain so the product gives
    # real AI answers out-of-the-box with no API key and $0 cost. Cloud
    # providers remain reachable via routing preferences / the fallback chain.
    "KO": ModelProvider.OLLAMA,
    "AV": ModelProvider.FLASH,
    "RU": ModelProvider.LOCAL,
    "CA": ModelProvider.SONNET,
    "UM": ModelProvider.GROK,
    "DR": ModelProvider.HAIKU,
}

_HIGH_KEYWORDS = {
    "compare",
    "analyze",
    "report",
    "competitors",
    "structured",
    "citations",
    "comprehensive",
    "evaluate",
}
_LOW_KEYWORDS = {"what", "when", "who", "define", "list", "ping"}


@dataclass
class SelectedModel:
    provider: ModelProvider
    role: str
    complexity: TaskComplexity
    selection_reason: str
    fallback_chain: list[ModelProvider]


@dataclass
class ProviderStatus:
    provider: ModelProvider
    family: str
    available: bool
    reason: str
    env_vars: tuple[str, ...]
    tier: int


class OctoArmorRouter:
    def __init__(
        self,
        preferences: dict[str, ModelProvider] | None = None,
        enabled_providers: dict[ModelProvider, bool] | None = None,
        local_first: bool = True,
    ):
        self._prefs = {**DEFAULT_PREFERENCES, **(preferences or {})}
        self._rate_limits: dict[ModelProvider, float] = {}
        self._enabled_overrides = dict(enabled_providers or {})
        self._local_first = local_first

    def get_preferences(self) -> dict[str, ModelProvider]:
        return dict(self._prefs)

    @staticmethod
    def normalize_preferences(
        raw_preferences: dict[str, Any] | None,
    ) -> dict[str, ModelProvider]:
        normalized: dict[str, ModelProvider] = {}
        if not raw_preferences:
            return normalized
        for role, provider in raw_preferences.items():
            try:
                normalized[str(role)] = (
                    provider if isinstance(provider, ModelProvider) else ModelProvider(str(provider))
                )
            except ValueError:
                continue
        return normalized

    def provider_status_snapshot(self) -> dict[str, dict[str, object]]:
        return {
            provider.value: {
                "available": status.available,
                "family": status.family,
                "reason": status.reason,
                "env_vars": list(status.env_vars),
                "tier": status.tier,
            }
            for provider, status in self.provider_status().items()
        }

    def provider_status(self) -> dict[ModelProvider, ProviderStatus]:
        snapshot: dict[ModelProvider, ProviderStatus] = {}
        for provider in ModelProvider:
            available, reason = self._configured_available(provider)
            snapshot[provider] = ProviderStatus(
                provider=provider,
                family=PROVIDER_FAMILY[provider],
                available=available,
                reason=reason,
                env_vars=PROVIDER_ENV_VARS[provider],
                tier=MODEL_COST_TIER[provider],
            )
        return snapshot

    def score_complexity(self, text: str) -> TaskComplexity:
        words = set(text.lower().split())
        high_hits = len(words & _HIGH_KEYWORDS)
        low_hits = len(words & _LOW_KEYWORDS)
        word_count = len(text.split())
        if high_hits >= 2 or word_count > 50:
            return TaskComplexity.HIGH
        if low_hits >= 1 and word_count < 15:
            return TaskComplexity.LOW
        return TaskComplexity.MEDIUM

    def mark_rate_limited(self, provider: ModelProvider, window_sec: float = 60.0) -> None:
        self._rate_limits[provider] = time.monotonic() + window_sec

    def _configured_available(self, provider: ModelProvider) -> tuple[bool, str]:
        if provider in self._enabled_overrides:
            enabled = self._enabled_overrides[provider]
            return enabled, "override_enabled" if enabled else "override_disabled"
        env_vars = PROVIDER_ENV_VARS[provider]
        if not env_vars:
            return True, "local_runtime"
        if any(os.environ.get(name, "").strip() for name in env_vars):
            return True, f"env:{env_vars[0]}"
        return False, f"missing_env:{','.join(env_vars)}"

    def _is_available(self, provider: ModelProvider) -> bool:
        configured, _ = self._configured_available(provider)
        if not configured:
            return False
        expiry = self._rate_limits.get(provider)
        if expiry is None:
            return True
        if time.monotonic() >= expiry:
            del self._rate_limits[provider]
            return True
        return False

    def select_model(
        self,
        complexity: TaskComplexity,
        role: str,
        *,
        preference_overrides: dict[str, Any] | None = None,
        allow_fallback: bool = True,
        local_first: bool | None = None,
    ) -> SelectedModel:
        min_tier = COMPLEXITY_MIN_TIER[complexity]
        overrides = self.normalize_preferences(preference_overrides)
        explicit_preference = role in overrides
        preferred = overrides.get(role, self._prefs.get(role, ModelProvider.SONNET))
        use_local_first = self._local_first if local_first is None else local_first

        # The "local first" lane prefers the real local Ollama brain when it is
        # reachable, falling back to the deterministic LOCAL stub only if Ollama
        # is disabled. This keeps low-complexity answers real AI at $0.
        local_lane = (
            ModelProvider.OLLAMA if self._is_available(ModelProvider.OLLAMA)
            else ModelProvider.GITHUB if self._is_available(ModelProvider.GITHUB)  # free frontier before the dumb stub
            else ModelProvider.LOCAL
        )
        if (
            use_local_first
            and not explicit_preference
            and complexity == TaskComplexity.LOW
            and self._is_available(local_lane)
        ):
            fallback_chain = self._candidate_chain(min_tier=min_tier)
            return SelectedModel(
                provider=local_lane,
                role=role,
                complexity=complexity,
                selection_reason="local_first_low_complexity",
                fallback_chain=(fallback_chain if allow_fallback else [local_lane]),
            )

        if self._is_available(preferred):
            if explicit_preference:
                reason = (
                    "preference_override"
                    if MODEL_COST_TIER[preferred] >= min_tier
                    else "preference_override_below_recommended_tier"
                )
            else:
                reason = (
                    "preferred_provider"
                    if MODEL_COST_TIER[preferred] >= min_tier
                    else "preferred_provider_below_recommended_tier"
                )
            return SelectedModel(
                provider=preferred,
                role=role,
                complexity=complexity,
                selection_reason=reason,
                fallback_chain=(self._candidate_chain(min_tier=min_tier) if allow_fallback else [preferred]),
            )

        if not allow_fallback:
            raise RuntimeError(f"Preferred provider '{preferred.value}' unavailable and auto-cascade disabled")

        candidates = self._candidate_chain(min_tier=min_tier)
        if not candidates:
            # CI/offline-safe behavior: if no provider meets the recommended tier and
            # no remote keys are configured, fall back to LOCAL rather than hard-fail.
            #
            # This keeps integration tests deterministic and lets users run the
            # command planner in "no keys" environments while still exposing that
            # the selection is below the recommended cost tier.
            if self._is_available(ModelProvider.LOCAL):
                return SelectedModel(
                    provider=ModelProvider.LOCAL,
                    role=role,
                    complexity=complexity,
                    selection_reason="local_last_resort_below_recommended_tier",
                    fallback_chain=[ModelProvider.LOCAL],
                )
            raise RuntimeError("All models rate-limited or unavailable")
        return SelectedModel(
            provider=candidates[0],
            role=role,
            complexity=complexity,
            selection_reason="fallback_chain",
            fallback_chain=candidates,
        )

    def _candidate_chain(self, *, min_tier: int) -> list[ModelProvider]:
        chain = sorted(
            [p for p in ModelProvider if self._is_available(p) and MODEL_COST_TIER[p] >= min_tier],
            key=lambda p: MODEL_COST_TIER[p],
        )
        # Always keep the keyless local lanes as last-resort fallbacks so the
        # product never hard-fails with zero cloud keys: the real local Ollama
        # brain first, then the deterministic LOCAL stub as the final fallback.
        for floor in (ModelProvider.OLLAMA, ModelProvider.LOCAL):
            if self._is_available(floor) and floor not in chain:
                chain.append(floor)
        return chain
