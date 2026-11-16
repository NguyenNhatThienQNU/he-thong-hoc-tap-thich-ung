"""Nhà cung cấp AI: Google Gemini (thư viện google-genai, API generateContent, đầu ra JSON theo lược đồ).

Hỗ trợ cơ chế Multi-Key Pool (xoay vòng nhiều API key dự phòng) và
Model Fallback Cascade (tự động chuyển sang mô hình dự phòng khi máy chủ quá tải).
"""

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


def _friendly_error(exc: Exception | None, model: str) -> str:
    if exc is None:
        return "Không nhận được phản hồi từ dịch vụ AI."
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    msg_lower = message.lower()
    if code in (400, 401, 403) and ("key" in msg_lower or "permission" in msg_lower):
        return "Khóa GEMINI_API_KEY không hợp lệ hoặc chưa được kích hoạt."
    if code == 404:
        return f"Không tìm thấy mô hình '{model}'. Hệ thống đã thử các mô hình dự phòng nhưng không thành công."
    if code == 429 or "quota" in msg_lower or "resource_exhausted" in msg_lower:
        return "Đã đạt giới hạn hạn mức API (Quota). Hệ thống đang tự động điều phối lại, vui lòng thử lại sau ít giây."
    if code == 503 or "high demand" in msg_lower or "overloaded" in msg_lower:
        return "Máy chủ AI của Google đang có lượng truy cập đột biến. Hãy nhấn 'Thử lại' sau giây lát."
    return f"Lỗi Gemini ({code}): {message[:300]}"


def _parts_text(content) -> str:
    if content is None or not content.parts:
        return ""
    return "".join(p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False))


class GeminiProvider(AIProvider):
    name = "gemini"
    is_real = True

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 120,
        api_keys: str = "",
        fallback_models: str = "",
    ):
        from google import genai
        from google.genai import types

        # 1. Trích xuất tất cả API Key (hỗ trợ nhiều key cách nhau bằng dấu phẩy, chấm phẩy hoặc xuống dòng)
        combined_keys = f"{api_key}\n{api_keys}"
        keys = []
        for token in re.split(r"[,;\n\s]+", combined_keys):
            token = token.strip()
            if token and token not in keys:
                keys.append(token)

        if not keys:
            raise AIError("Chưa cấu hình GEMINI_API_KEY.")

        self.keys = keys
        self.types = types
        self.timeout_seconds = timeout_seconds

        # 2. Xây dựng danh sách mô hình chính và danh sách mô hình dự phòng (Model Cascade)
        primary = model.strip() if model.strip() else "gemini-flash-latest"
        models = [primary]

        defaults = [
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-flash-latest",
            "gemini-1.5-flash-8b",
            "gemini-1.5-pro",
        ]
        extra_models = [m.strip() for m in re.split(r"[,;\n\s]+", fallback_models) if m.strip()]
        for m in extra_models + defaults:
            if m and m not in models:
                models.append(m)

        self.models = models
        self.model = primary

        # Bộ nhớ đệm Client và trạng thái quản lý Cooldown / Load-balancing
        self._clients: dict[str, genai.Client] = {}
        self._key_cooldown: dict[str, float] = {}
        self._key_index: int = 0

        log.info(
            "Đã khởi tạo GeminiProvider với %d API key và %d mô hình (Chính: %s, Dự phòng: %s)",
            len(self.keys),
            len(self.models),
            self.model,
            ", ".join(self.models[1:]),
        )

    def _get_client(self, key: str):
        if key not in self._clients:
            from google import genai

            self._clients[key] = genai.Client(
                api_key=key,
                http_options=self.types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),
            )
        return self._clients[key]

    def _get_active_keys(self) -> list[str]:
        now = time.time()
        available = [k for k in self.keys if self._key_cooldown.get(k, 0) <= now]
        if not available:
            earliest = min(self.keys, key=lambda k: self._key_cooldown.get(k, 0))
            return [earliest]
        # Xoay vòng round-robin để phân tán tải đều giữa các key
        idx = self._key_index % len(available)
        self._key_index += 1
        return available[idx:] + available[:idx]

    # ------------------------------------------------------------------
    def _generate(self, contents, config):
        """Gọi generateContent với cơ chế Multi-Key Pool (xoay vòng key) và Model Fallback Cascade (chuyển mô hình dự phòng khi quá tải)."""
        from google.genai import errors

        last_exc = None
        for model_idx, model in enumerate(self.models):
            active_keys = self._get_active_keys()
            for key_idx, key in enumerate(active_keys):
                masked_key = f"...{key[-4:]}" if len(key) >= 4 else "***"
                client = self._get_client(key)

                try:
                    resp = client.models.generate_content(model=model, contents=contents, config=config)
                    # Thành công: xóa cooldown cho key này
                    self._key_cooldown.pop(key, None)
                    if model_idx > 0 or key_idx > 0:
                        log.info(
                            "Gemini xử lý thành công nhờ cơ chế dự phòng (Mô hình: %s, Key: %s)",
                            model,
                            masked_key,
                        )
                    return resp
                except errors.APIError as exc:
                    last_exc = exc
                    code = getattr(exc, "code", None)
                    msg = getattr(exc, "message", None) or str(exc)
                    msg_lower = msg.lower()

                    is_high_demand = (
                        ("high demand" in msg_lower)
                        or ("spikes in demand" in msg_lower)
                        or ("overloaded" in msg_lower)
                        or (code == 503)
                    )
                    is_quota = (
                        (code == 429)
                        or ("resource_exhausted" in msg_lower)
                        or ("quota" in msg_lower)
                    )
                    is_key_invalid = (code in (400, 401, 403)) and (
                        "key" in msg_lower or "permission" in msg_lower
                    )
                    is_not_found = code == 404

                    if is_quota or is_key_invalid:
                        # Key này bị hạn mức (429) hoặc sai key: Đưa vào cooldown 60s và chuyển ngay sang Key tiếp theo
                        self._key_cooldown[key] = time.time() + 60.0
                        log.warning(
                            "Gemini Key %s gặp lỗi hạn mức (%s). Tự động chuyển sang Key dự phòng tiếp theo...",
                            masked_key,
                            code,
                        )
                        continue
                    elif is_high_demand or is_not_found:
                        # Máy chủ mô hình đang quá tải (503): Chuyển sang mô hình dự phòng tiếp theo
                        log.warning(
                            "Mô hình Gemini '%s' đang quá tải lượng truy cập (503 / High demand). Tự động chuyển sang mô hình dự phòng...",
                            model,
                        )
                        break
                    else:
                        log.info("Gemini lỗi tạm thời (%s) trên Key %s: %s", code, masked_key, msg[:100])
                        continue
                except Exception as exc:
                    last_exc = exc
                    log.warning("Lỗi kết nối Gemini trên Key %s: %s", masked_key, exc)
                    continue

        raise AIError(_friendly_error(last_exc, self.models[0])) from last_exc

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
