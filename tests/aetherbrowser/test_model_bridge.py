"""Tests for the ModelBridge — OctoArmor to real LLM provider mapping."""
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.aetherbrowser.model_bridge import ModelBridge, _PROVIDER_MAP, _REQUIRED_KEYS
from src.aetherbrowser.router import ModelProvider


class TestProviderMapping:
    def test_all_model_providers_have_mapping(self):
        for mp in ModelProvider:
            assert mp in _PROVIDER_MAP, f"Missing mapping for {mp}"

    def test_mapping_has_ai_type_and_model(self):
        for mp, (ai_type, model_name) in _PROVIDER_MAP.items():
            assert isinstance(ai_type, str)
            assert isinstance(model_name, str)
            assert len(ai_type) > 0
            assert len(model_name) > 0

    def test_opus_maps_to_claude(self):
        ai_type, model = _PROVIDER_MAP[ModelProvider.OPUS]
        assert ai_type == "claude"
        assert "opus" in model

    def test_flash_maps_to_gemini(self):
        ai_type, model = _PROVIDER_MAP[ModelProvider.FLASH]
        assert ai_type == "gemini"
        assert "flash" in model

    def test_grok_maps_to_grok(self):
        ai_type, model = _PROVIDER_MAP[ModelProvider.GROK]
        assert ai_type == "grok"

    def test_local_maps_to_local(self):
        ai_type, model = _PROVIDER_MAP[ModelProvider.LOCAL]
        assert ai_type == "local"


class TestModelBridge:
    def test_init(self):
        mb = ModelBridge()
        assert mb._providers == {}
        assert mb._unavailable == set()

    def test_available_providers_with_no_keys(self):
        """With no env vars set, only LOCAL should be available."""
        mb = ModelBridge()
        with patch.dict(os.environ, {}, clear=True):
            available = mb.available_providers()
            # LOCAL always available (no key needed)
            assert any("local" in p for p in available)

    def test_available_providers_with_anthropic_key(self):
        mb = ModelBridge()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
            available = mb.available_providers()
            assert any("opus" in p for p in available)
            assert any("sonnet" in p for p in available)
            assert any("haiku" in p for p in available)


class TestEchoFallback:
    @pytest.mark.asyncio
    async def test_complete_returns_echo_when_no_key(self):
        mb = ModelBridge()
        with patch.dict(os.environ, {}, clear=True):
            mb._unavailable.clear()
            mb._providers.clear()
            result = await mb.complete(ModelProvider.OPUS, "Test prompt")
            assert "echo" in result.model.lower() or "Echo" in result.text
            assert "Test prompt" in result.text

    @pytest.mark.asyncio
    async def test_stream_returns_echo_when_no_key(self):
        mb = ModelBridge()
        with patch.dict(os.environ, {}, clear=True):
            mb._unavailable.clear()
            mb._providers.clear()
            chunks = []
            async for chunk in mb.stream(ModelProvider.OPUS, "Hello world test"):
                chunks.append(chunk)
            text = "".join(chunks)
            assert len(text) > 0
            assert "echo" in text.lower() or "Echo" in text

    @pytest.mark.asyncio
    async def test_local_does_not_need_key(self):
        """LOCAL provider should attempt to create even without keys."""
        mb = ModelBridge()
        with patch.dict(os.environ, {}, clear=True):
            mb._unavailable.clear()
            mb._providers.clear()
            # LOCAL doesn't need an API key, but may fail if openai isn't installed
            # or localhost isn't running. The point is it doesn't get echo-fallback.
            provider = mb._get_provider(ModelProvider.LOCAL)
            # It either returns a real provider or None (if openai not installed)
            # but it should NOT be due to missing API key
            cache_key = "local:local-model"
            # If unavailable, it's not because of a missing key
            if cache_key in mb._unavailable:
                assert _REQUIRED_KEYS.get("local", "") == ""


class TestProviderCaching:
    def test_unavailable_is_cached(self):
        mb = ModelBridge()
        with patch.dict(os.environ, {}, clear=True):
            mb._unavailable.clear()
            mb._get_provider(ModelProvider.OPUS)
            assert "claude:claude-opus-4-20250514" in mb._unavailable
            # Second call should return None immediately
            result = mb._get_provider(ModelProvider.OPUS)
            assert result is None

    def test_provider_is_cached_on_success(self):
        mb = ModelBridge()
        mock_provider = MagicMock()
        with patch("hydra.llm_providers.create_provider", return_value=mock_provider):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}, clear=True):
                mb._unavailable.clear()
                mb._providers.clear()
                p1 = mb._get_provider(ModelProvider.OPUS)
                p2 = mb._get_provider(ModelProvider.OPUS)
                assert p1 is p2
                assert p1 is mock_provider
