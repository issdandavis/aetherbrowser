"""
Model Bridge — OctoArmor -> Real LLM Providers
================================================

Maps OctoArmor's ModelProvider enum to hydra/llm_providers.py's
create_provider() factory. Handles missing API keys gracefully
by falling back to an echo provider.

Usage:
    bridge = ModelBridge()
    response = await bridge.complete("opus", "Explain SCBE governance")
    async for chunk in bridge.stream("sonnet", "Plan a web scrape"):
        print(chunk, end="")
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from src.aetherbrowser.router import ModelProvider

logger = logging.getLogger("aetherbrowser.model_bridge")

# Map OctoArmor enum -> (llm_providers ai_type, default model)
_PROVIDER_MAP: dict[ModelProvider, tuple[str, str]] = {
    ModelProvider.OPUS: ("claude", "claude-opus-4-20250514"),
    ModelProvider.SONNET: ("claude", "claude-sonnet-4-20250514"),
    ModelProvider.HAIKU: ("claude", "claude-haiku-4-5-20251001"),
    ModelProvider.FLASH: ("gemini", "gemini-2.0-flash"),
    ModelProvider.GROK: ("grok", "grok-3-mini"),
    ModelProvider.LOCAL: ("local", "local-model"),
}

# Which env var each provider needs
_REQUIRED_KEYS: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "grok": "XAI_API_KEY",
    "gpt": "OPENAI_API_KEY",
    "local": "",  # No key needed
}


@dataclass
class BridgeResponse:
    text: str
    model: str
    provider_name: str
    input_tokens: int = 0
    output_tokens: int = 0


class ModelBridge:
    """Lazy-initializes LLM providers on first use, caches them."""

    def __init__(self):
        self._providers: dict[str, object] = {}
        self._unavailable: set[str] = set()

    def _get_provider(self, model_enum: ModelProvider):
        """Get or create an LLM provider for the given model enum."""
        ai_type, model_name = _PROVIDER_MAP.get(
            model_enum, ("claude", "claude-sonnet-4-20250514")
        )

        cache_key = f"{ai_type}:{model_name}"
        if cache_key in self._unavailable:
            return None
        if cache_key in self._providers:
            return self._providers[cache_key]

        # Check if required API key is present
        required_key = _REQUIRED_KEYS.get(ai_type, "")
        if required_key and not os.environ.get(required_key):
            logger.warning(
                f"Missing {required_key} for {ai_type} provider. "
                f"Will use echo fallback."
            )
            self._unavailable.add(cache_key)
            return None

        try:
            from hydra.llm_providers import create_provider
            provider = create_provider(ai_type, model=model_name)
            self._providers[cache_key] = provider
            return provider
        except Exception as e:
            logger.warning(f"Failed to create {ai_type} provider: {e}")
            self._unavailable.add(cache_key)
            return None

    async def complete(
        self,
        model_enum: ModelProvider,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> BridgeResponse:
        """Complete a prompt using the mapped LLM provider."""
        ai_type, model_name = _PROVIDER_MAP.get(
            model_enum, ("claude", "claude-sonnet-4-20250514")
        )

        provider = self._get_provider(model_enum)
        if provider is None:
            # Echo fallback — return prompt summary
            return BridgeResponse(
                text=f"[Echo: no {ai_type} API key set] Received: {prompt[:200]}",
                model=f"echo-{ai_type}",
                provider_name=ai_type,
            )

        response = await provider.complete(
            prompt=prompt, system=system, max_tokens=max_tokens
        )
        return BridgeResponse(
            text=response.text,
            model=response.model,
            provider_name=ai_type,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    async def stream(
        self,
        model_enum: ModelProvider,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream completion tokens from the mapped LLM provider."""
        ai_type, _ = _PROVIDER_MAP.get(
            model_enum, ("claude", "claude-sonnet-4-20250514")
        )

        provider = self._get_provider(model_enum)
        if provider is None:
            yield f"[Echo: no {ai_type} API key] "
            for word in prompt.split()[:20]:
                yield word + " "
            return

        async for chunk in provider.stream(
            prompt=prompt, system=system, max_tokens=max_tokens
        ):
            yield chunk

    def available_providers(self) -> list[str]:
        """List which providers have valid API keys."""
        available = []
        for model_enum, (ai_type, _) in _PROVIDER_MAP.items():
            required_key = _REQUIRED_KEYS.get(ai_type, "")
            if not required_key or os.environ.get(required_key):
                available.append(f"{model_enum.value}:{ai_type}")
        return available
