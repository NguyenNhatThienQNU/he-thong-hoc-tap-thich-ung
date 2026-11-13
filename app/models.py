"""Mô hình dữ liệu (SQLAlchemy 2).

Sơ đồ chính:
  Teacher ─< Course ─< Topic ─< Question
                 ├─< Material ─< Chunk          (kho tri thức do giáo viên kiểm duyệt)
                 ├─< Exam ─< ExamAttempt        (bài đầu vào, sau học, ghi nhớ)
                 └─< Classroom ─< Student ─< Mastery (mức nắm vững theo chủ đề)
                                         └─< PracticeSession ─< Message (nhật ký tương tác với AI)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .utils.text import OPTION_LETTERS, split_lines
from .utils.timeutil import utcnow

# ---------------------------------------------------------------------------
# Hằng số hiển thị
# ---------------------------------------------------------------------------

MODE_ADAPTIVE = "adaptive"
MODE_DIRECT = "direct"
MODE_LABELS = {
    MODE_ADAPTIVE: "AI hỗ trợ thích ứng",
    MODE_DIRECT: "AI giải trực tiếp",
}
MODE_GROUPS = {
    MODE_ADAPTIVE: "Nhóm thực nghiệm",
    MODE_DIRECT: "Nhóm đối chứng",
}

QUESTION_KINDS = {"mcq": "Trắc nghiệm", "short": "Trả lời ngắn", "open": "Tự luận ngắn"}
DIFFICULTY = {1: "Nhận biết", 2: "Thông hiểu", 3: "Vận dụng", 4: "Vận dụng cao"}
PURPOSES = {"practice": "Luyện tập", "test": "Kiểm tra", "both": "Luyện tập và kiểm tra"}
QUESTION_STATUS = {"draft": "Nháp – chờ duyệt", "approved": "Đã duyệt", "archived": "Đã ẩn"}
MATERIAL_STATUS = {"pending": "Chờ duyệt", "approved": "Đã duyệt"}
EXAM_KINDS = {
    "pre": "Đầu vào",
    "post": "Ngay sau học",
    "retention": "Ghi nhớ (trì hoãn)",
    "other": "Luyện thi khác",
}

# Bậc thang gợi ý: mức càng cao, AI hỗ trợ càng nhiều
HINT_LEVELS = {
    1: ("Định hướng", "Câu hỏi gợi mở giúp em xác định đề hỏi gì, đã biết gì."),
    2: ("Gợi nhắc kiến thức", "Nhắc lại khái niệm, quy tắc liên quan trong tài liệu của giáo viên."),
    3: ("Gợi ý cách làm", "Nêu hướng giải hoặc bước đầu tiên, không làm thay."),
    4: ("Làm mẫu một phần", "Hướng dẫn các bước trung gian, để em tự hoàn thành bước cuối."),
    5: ("Lời giải chi tiết", "Lời giải đầy đủ, chỉ mở khi em đã thử đủ số lần."),
}

DIFFICULTY_TYPES = {
    "chua_hieu_de": "Chưa hiểu yêu cầu đề",
    "chua_bat_dau": "Chưa biết bắt đầu từ đâu",
    "thieu_kien_thuc": "Chưa nắm kiến thức liên quan",
    "sai_phuong_phap": "Chọn chưa đúng hướng làm",
    "sai_sot": "Sai sót nhỏ (tính toán, cú pháp)",
    "khac": "Khác",
}

DEFAULT_POLICY = {
    # Học sinh phải viết hướng làm / chỗ đang vướng trước khi nhận gợi ý
    "require_attempt_first": True,
    # Số lần trả lời sai tối thiểu trước khi được mở lời giải chi tiết (mức 5)
    "min_attempts_for_solution": 2,
    # Giảm dần mức hỗ trợ khi mức nắm vững tăng
    "fading": True,
    # Trần mức gợi ý khi học sinh đã nắm vững chủ đề (p ≥ 0,7) và chưa thử đủ số lần
    "max_level_mastered": 3,
}


# ---------------------------------------------------------------------------
# Giáo viên, môn học, chủ đề
# ---------------------------------------------------------------------------


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    courses: Mapped[list[Course]] = relationship(back_populates="teacher", order_by="Course.id")
    classes: Mapped[list[Classroom]] = relationship(back_populates="teacher", order_by="Classroom.name")


class Course(Base):
    """Môn học / khóa học: chứa chủ đề, kho tri thức, ngân hàng câu hỏi và bài kiểm tra."""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    grade: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    teacher: Mapped[Teacher] = relationship(back_populates="courses")
    topics: Mapped[list[Topic]] = relationship(
        back_populates="course", order_by=lambda: [Topic.position, Topic.id], cascade="all, delete-orphan"
    )
    materials: Mapped[list[Material]] = relationship(
        back_populates="course", order_by="Material.id", cascade="all, delete-orphan"
    )
    questions: Mapped[list[Question]] = relationship(
        back_populates="course", order_by="Question.id", cascade="all, delete-orphan"
    )
    exams: Mapped[list[Exam]] = relationship(back_populates="course", order_by="Exam.id", cascade="all, delete-orphan")
    classes: Mapped[list[Classroom]] = relationship(back_populates="course", order_by="Classroom.name")

    def policy_value(self, key: str):
        return (self.policy or {}).get(key, DEFAULT_POLICY[key])

    @property
    def full_policy(self) -> dict:
        return {key: self.policy_value(key) for key in DEFAULT_POLICY}


class Topic(Base):
    """Chủ đề / đơn vị kiến thức trong lộ trình học."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    prerequisite_ids: Mapped[list] = mapped_column(JSON, default=list)

    course: Mapped[Course] = relationship(back_populates="topics")
    questions: Mapped[list[Question]] = relationship(back_populates="topic", order_by="Question.id")
    materials: Mapped[list[Material]] = relationship(back_populates="topic", order_by="Material.id")


# ---------------------------------------------------------------------------
# Kho tri thức
# ---------------------------------------------------------------------------


class Material(Base):
    """Tài liệu học tập. Chỉ tài liệu đã được giáo viên duyệt mới được AI dùng để gợi ý."""

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    course: Mapped[Course] = relationship(back_populates="materials")
    topic: Mapped[Topic | None] = relationship(back_populates="materials")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="material", order_by="Chunk.position", cascade="all, delete-orphan"
    )

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def word_count(self) -> int:
        return len((self.content or "").split())


class Chunk(Base):
    """Đoạn tri thức (đã cắt nhỏ) để tra cứu khi AI gợi ý."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(Integer, index=True)
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)

    material: Mapped[Material] = relationship(back_populates="chunks")


# ---------------------------------------------------------------------------
# Câu hỏi và bài kiểm tra
# ---------------------------------------------------------------------------


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="short")  # mcq | short | open
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    correct_option: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer: Mapped[str] = mapped_column(Text, default="")  # đáp án chấp nhận, mỗi dòng một cách viết
    solution: Mapped[str] = mapped_column(Text, default="")  # lời giải, mỗi dòng một bước
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    purpose: Mapped[str] = mapped_column(String(10), default="practice")
    status: Mapped[str] = mapped_column(String(10), default="approved")
    source: Mapped[str] = mapped_column(String(10), default="teacher")  # teacher | ai | demo
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    course: Mapped[Course] = relationship(back_populates="questions")
    topic: Mapped[Topic] = relationship(back_populates="questions")

    @property
    def options_list(self) -> list[str]:
        return [str(o) for o in (self.options or [])]

    @property
    def accepted_answers(self) -> list[str]:
        out: list[str] = []
        for line in (self.answer or "").replace("|", "\n").splitlines():
            if line.strip():
                out.append(line.strip())
        return out

    @property
    def solution_steps(self) -> list[str]:
        return split_lines(self.solution)

    @property
    def final_answer_text(self) -> str:
        if self.kind == "mcq":
            opts = self.options_list
            if self.correct_option is not None and 0 <= self.correct_option < len(opts):
                return f"{OPTION_LETTERS[self.correct_option]}. {opts[self.correct_option]}"
            return "(chưa đặt đáp án)"
        answers = self.accepted_answers
        return answers[0] if answers else "(chưa có đáp án)"

    @property
    def for_practice(self) -> bool:
        return self.purpose in ("practice", "both")

    @property
    def for_test(self) -> bool:
        return self.purpose in ("test", "both")

    def as_text(self) -> str:
        """Đề bài dạng văn bản (kèm phương án nếu là trắc nghiệm) để gửi cho AI."""
        text = self.stem.strip()
        if self.kind == "mcq":
            text += "\n" + "\n".join(f"{OPTION_LETTERS[i]}. {o}" for i, o in enumerate(self.options_list))
        return text


class Exam(Base):
    """Bài kiểm tra không có AI: đầu vào, ngay sau học, ghi nhớ (trì hoãn)."""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(12), default="other")
    question_ids: Mapped[list] = mapped_column(JSON, default=list)
    duration_min: Mapped[int] = mapped_column(Integer, default=20)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False)
    show_answers: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    course: Mapped[Course] = relationship(back_populates="exams")
    attempts: Mapped[list[ExamAttempt]] = relationship(back_populates="exam", cascade="all, delete-orphan")


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    __table_args__ = (UniqueConstraint("exam_id", "student_id", name="uq_attempt_exam_student"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # thang 10

    exam: Mapped[Exam] = relationship(back_populates="attempts")
    student: Mapped[Student] = relationship(back_populates="exam_attempts")


# ---------------------------------------------------------------------------
# Lớp, học sinh, mức nắm vững
# ---------------------------------------------------------------------------


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    default_mode: Mapped[str] = mapped_column(String(10), default=MODE_ADAPTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    teacher: Mapped[Teacher] = relationship(back_populates="classes")
    course: Mapped[Course] = relationship(back_populates="classes")
    students: Mapped[list[Student]] = relationship(
        back_populates="classroom", order_by="Student.full_name", cascade="all, delete-orphan"
    )


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    student_code: Mapped[str] = mapped_column(String(40), default="")
    login_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    mode: Mapped[str | None] = mapped_column(String(10), nullable=True)  # None = theo mặc định của lớp
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    classroom: Mapped[Classroom] = relationship(back_populates="students")
    masteries: Mapped[list[Mastery]] = relationship(back_populates="student", cascade="all, delete-orphan")
    sessions: Mapped[list[PracticeSession]] = relationship(
        back_populates="student", order_by="PracticeSession.id", cascade="all, delete-orphan"
    )
    exam_attempts: Mapped[list[ExamAttempt]] = relationship(back_populates="student", cascade="all, delete-orphan")

    @property
    def effective_mode(self) -> str:
        return self.mode or self.classroom.default_mode or MODE_ADAPTIVE

    @property
    def first_name(self) -> str:
        parts = self.full_name.split()
        return parts[-1] if parts else self.full_name


class Mastery(Base):
    """Xác suất học sinh đã nắm vững một chủ đề (mô hình Bayesian Knowledge Tracing)."""

    __tablename__ = "masteries"
    __table_args__ = (UniqueConstraint("student_id", "topic_id", name="uq_mastery_student_topic"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    p_known: Mapped[float] = mapped_column(Float, default=0.3)
    n_obs: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    student: Mapped[Student] = relationship(back_populates="masteries")
    topic: Mapped[Topic] = relationship()


# ---------------------------------------------------------------------------
# Phiên luyện tập và nhật ký tương tác với AI
# ---------------------------------------------------------------------------


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    __table_args__ = (Index("ix_session_student_started", "student_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    topic_id: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(10), default=MODE_ADAPTIVE)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | solved | given_up
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # số lần nộp đáp án
    wrong_attempts: Mapped[int] = mapped_column(Integer, default=0)
    hint_requests: Mapped[int] = mapped_column(Integer, default=0)  # số lần nhờ AI hỗ trợ
    max_hint_level: Mapped[int] = mapped_column(Integer, default=0)  # 0 = không cần gợi ý, 5 = xem lời giải
    solution_viewed: Mapped[bool] = mapped_column(Boolean, default=False)
    independent: Mapped[bool] = mapped_column(Boolean, default=False)  # tự lực: đúng, gợi ý tối đa mức 1
    last_difficulty: Mapped[str | None] = mapped_column(String(20), nullable=True)
    wrong_options: Mapped[list] = mapped_column(JSON, default=list)
    p_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    student: Mapped[Student] = relationship(back_populates="sessions")
    question: Mapped[Question] = relationship()
    messages: Mapped[list[Message]] = relationship(
        back_populates="session", order_by="Message.id", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def duration_seconds(self) -> int | None:
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds())

    @property
    def status_label(self) -> str:
        if self.status == "active":
            return "Đang làm"
        if self.status == "given_up":
            return "Bỏ qua"
        if self.independent:
            return "Tự giải được"
        if self.solution_viewed:
            return "Đúng sau khi xem lời giải"
        return "Đúng nhờ gợi ý"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # student | ai | system
    kind: Mapped[str] = mapped_column(String(12))  # answer | help | hint | ask | reply | solution | feedback
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped[PracticeSession] = relationship(back_populates="messages")
