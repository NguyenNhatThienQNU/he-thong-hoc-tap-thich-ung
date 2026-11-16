"""Lớp AI: gợi ý thích ứng, giải trực tiếp (nhóm đối chứng), chấm câu trả lời, soạn câu hỏi nháp."""

from __future__ import annotations

import logging

from ..config import Settings
from .base import AIError, AIProvider
from .mock import MockProvider

log = logging.getLogger(__name__)


def build_provider(settings: Settings) -> AIProvider:
    provider = settings.effective_ai_provider
    if provider == "gemini":
        from .gemini import GeminiProvider

        try:
            return GeminiProvider(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                timeout_seconds=settings.ai_timeout_seconds,
                api_keys=getattr(settings, "gemini_api_keys", ""),
                fallback_models=getattr(settings, "gemini_fallback_models", ""),
            )
        except AIError as exc:
            log.warning("Không khởi tạo được Gemini (%s) – chuyển sang chế độ demo.", exc)
    elif provider != "mock":
        log.warning("AI_PROVIDER '%s' không hỗ trợ – dùng chế độ demo.", provider)
    return MockProvider()


__all__ = ["AIError", "AIProvider", "MockProvider", "build_provider"]
