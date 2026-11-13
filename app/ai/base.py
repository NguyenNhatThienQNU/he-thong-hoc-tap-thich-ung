"""Giao diện chung cho các nhà cung cấp AI (Gemini, chế độ demo...)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .schemas import (
    AskRequest,
    AskResult,
    GeneratedQuestion,
    HintRequest,
    HintResult,
    JudgeRequest,
    JudgeResult,
    QuestionGenRequest,
    SolutionRequest,
    SolutionResult,
)


class AIError(RuntimeError):
    """Lỗi khi gọi mô hình AI (mạng, hết hạn mức, phản hồi sai định dạng...)."""


class AIProvider(ABC):
    name: str = "base"
    is_real: bool = False  # False = chế độ demo, không gọi mô hình thật

    @abstractmethod
    def hint(self, request: HintRequest) -> HintResult:
        """Chẩn đoán khó khăn và đưa gợi ý đúng mức (chế độ thích ứng)."""

    @abstractmethod
    def ask(self, request: AskRequest) -> AskResult:
        """Trả lời câu hỏi tự do của học sinh trong phiên luyện tập."""

    @abstractmethod
    def solution(self, request: SolutionRequest) -> SolutionResult:
        """Lời giải đầy đủ (chế độ giải trực tiếp, hoặc mức 5 của chế độ thích ứng)."""

    @abstractmethod
    def judge(self, request: JudgeRequest) -> JudgeResult:
        """Chấm câu trả lời ngắn/tự luận khi so khớp tự động không kết luận được."""

    @abstractmethod
    def generate_questions(self, request: QuestionGenRequest) -> list[GeneratedQuestion]:
        """Soạn câu hỏi nháp từ tài liệu đã duyệt (giáo viên duyệt trước khi dùng)."""
