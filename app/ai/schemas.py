"""Cấu trúc dữ liệu trao đổi với lớp AI (Pydantic) – cũng là lược đồ JSON yêu cầu mô hình trả về."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DifficultyType = Literal["chua_hieu_de", "chua_bat_dau", "thieu_kien_thuc", "sai_phuong_phap", "sai_sot", "khac"]


class Snippet(BaseModel):
    id: int
    title: str
    text: str


class TutorContext(BaseModel):
    subject_name: str
    topic_name: str
    question_text: str
    question_kind: str = "short"
    reference_answer: str = ""
    reference_solution: list[str] = Field(default_factory=list)
    student_answers: list[str] = Field(default_factory=list)  # các lần trả lời chưa đúng
    history: list[tuple[str, str]] = Field(default_factory=list)  # (student|ai, nội dung)
    mastery: float = 0.3
    materials: list[Snippet] = Field(default_factory=list)


class HintRequest(TutorContext):
    level: int
    level_name: str
    level_instruction: str
    student_message: str = ""  # hướng làm / chỗ đang vướng em vừa viết
    previous_difficulty: str | None = None


class HintResult(BaseModel):
    difficulty_type: DifficultyType = Field(description="Loại khó khăn chính của học sinh")
    analysis: str = Field(description="Một câu nhận định ngắn cho giáo viên")
    hint: str = Field(description="Lời gợi ý gửi học sinh, đúng mức được yêu cầu")
    source_ids: list[int] = Field(default_factory=list, description="id các đoạn tài liệu đã dùng")


class AskRequest(TutorContext):
    mode: str  # adaptive | direct
    level_cap: int = 2  # chế độ thích ứng: không vượt quá mức này
    student_message: str


class AskResult(BaseModel):
    reply: str
    source_ids: list[int] = Field(default_factory=list)


class SolutionRequest(TutorContext):
    adaptive: bool = False  # True: lời giải mức 5 của chế độ thích ứng (kèm yêu cầu tự làm lại)


class SolutionResult(BaseModel):
    solution: str


class JudgeRequest(BaseModel):
    question_text: str
    kind: str
    reference_answer: str
    reference_solution: list[str] = Field(default_factory=list)
    student_answer: str


class JudgeResult(BaseModel):
    correct: bool
    feedback: str = Field(description="Một câu nhận xét, không nêu đáp án đúng")


class QuestionGenRequest(BaseModel):
    subject_name: str
    topic_name: str
    material_text: str
    count: int = 5
    difficulty: int = 2
    kind: str = "mixed"  # mcq | short | mixed


class GeneratedQuestion(BaseModel):
    kind: Literal["mcq", "short"]
    stem: str
    options: list[str] = Field(default_factory=list)
    correct_option: int | None = None
    answer: str = ""
    solution_steps: list[str] = Field(default_factory=list)
    difficulty: int = 2


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion]
