"""Nhà cung cấp AI: Google Gemini (thư viện google-genai, API generateContent, đầu ra JSON theo lược đồ)."""

from __future__ import annotations

import copy
import logging
import re
import time

from pydantic import BaseModel, ValidationError

from . import prompts
from .base import AIError, AIProvider
from .schemas import (
    AskRequest,
    AskResult,
    GeneratedQuestion,
    GeneratedQuestions,
    HintRequest,
    HintResult,
    JudgeRequest,
    JudgeResult,
    QuestionGenRequest,
    SolutionRequest,
    SolutionResult,
)

log = logging.getLogger(__name__)

RETRYABLE_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


def inline_schema(model: type[BaseModel]) -> dict:
    """Chuyển lược đồ Pydantic sang JSON Schema phẳng (thay $ref bằng định nghĩa, bỏ 'title')."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node, in_properties: bool = False):
        if isinstance(node, dict):
            if "$ref" in node and not in_properties:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {}
            for key, value in node.items():
                if not in_properties and key == "title" and isinstance(value, str):
                    continue
                out[key] = resolve(value, in_properties=(key == "properties" and not in_properties))
            return out
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


def _friendly_error(exc: Exception, model: str) -> str:
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    if code in (400, 401, 403) and "key" in message.lower():
        return "Khóa GEMINI_API_KEY không hợp lệ hoặc chưa được cấp quyền."
    if code == 404:
        return f"Không tìm thấy mô hình '{model}'. Kiểm tra lại GEMINI_MODEL trong tệp .env."
    if code == 429:
        return "Đã vượt hạn mức gọi Gemini (quota). Hãy thử lại sau ít phút."
    return f"Lỗi Gemini ({code}): {message[:300]}"


def _parts_text(content) -> str:
    if content is None or not content.parts:
        return ""
    return "".join(p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False))


class GeminiProvider(AIProvider):
    name = "gemini"
    is_real = True

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 120):
        from google import genai
        from google.genai import types

        if not api_key:
            raise AIError("Chưa cấu hình GEMINI_API_KEY.")
        self.types = types
        self.model = model
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)))

    # ------------------------------------------------------------------
    def _generate(self, contents, config):
        """Gọi generateContent, tự thử lại khi gặp lỗi tạm thời (quá tải, hết hạn mức)."""
        from google.genai import errors

        delay = 2.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.APIError as exc:
                if getattr(exc, "code", None) in RETRYABLE_CODES and attempt < MAX_ATTEMPTS:
                    log.info("Gemini lỗi tạm thời (%s), thử lại sau %.0fs", exc.code, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise AIError(_friendly_error(exc, self.model)) from exc
            except Exception as exc:  # lỗi mạng, hết thời gian chờ...
                if attempt < MAX_ATTEMPTS:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise AIError(f"Không kết nối được Gemini: {exc}") from exc
        raise AIError("Không gọi được Gemini.")

    def _json(self, prompt: str, system: str, model_cls: type[BaseModel]):
        types = self.types
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=inline_schema(model_cls),
        )
        response = self._generate([types.Content(role="user", parts=[types.Part(text=prompt)])], config)
        candidate = response.candidates[0] if response.candidates else None
        text = _parts_text(candidate.content if candidate else None)
        if not text:
            raise AIError("Gemini không trả về nội dung (có thể bị bộ lọc an toàn chặn).")
        try:
            return model_cls.model_validate_json(_strip_fences(text))
        except ValidationError as exc:
            raise AIError("Phản hồi của AI không đúng định dạng JSON mong đợi.") from exc

    # ------------------------------------------------------------------
    def hint(self, request: HintRequest) -> HintResult:
        return self._json(prompts.hint_prompt(request), prompts.adaptive_system(request.subject_name), HintResult)

    def ask(self, request: AskRequest) -> AskResult:
        system = (
            prompts.direct_system(request.subject_name)
            if request.mode == "direct"
            else prompts.adaptive_system(request.subject_name)
        )
        return self._json(prompts.ask_prompt(request), system, AskResult)

    def solution(self, request: SolutionRequest) -> SolutionResult:
        return self._json(prompts.solution_prompt(request), prompts.direct_system(request.subject_name), SolutionResult)

    def judge(self, request: JudgeRequest) -> JudgeResult:
        return self._json(prompts.judge_prompt(request), prompts.judge_system(), JudgeResult)

    def generate_questions(self, request: QuestionGenRequest) -> list[GeneratedQuestion]:
        result = self._json(
            prompts.question_prompt(request), prompts.question_system(request.subject_name), GeneratedQuestions
        )
        return result.questions
