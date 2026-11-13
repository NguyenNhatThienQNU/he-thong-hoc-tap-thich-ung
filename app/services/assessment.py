"""Bài kiểm tra không có AI (đầu vào, ngay sau học, ghi nhớ) – công cụ đo trong thực nghiệm."""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.base import AIProvider
from ..models import Exam, ExamAttempt, Question, Student
from ..utils.timeutil import utcnow
from .mastery import apply_evidence
from .tutor import check_answer

GRACE_SECONDS = 90


def exam_questions(db: Session, exam: Exam) -> list[Question]:
    ids = [int(i) for i in exam.question_ids or []]
    if not ids:
        return []
    by_id = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(ids))).all()}
    return [by_id[i] for i in ids if i in by_id]


def get_attempt(db: Session, exam: Exam, student: Student) -> ExamAttempt | None:
    return db.scalar(select(ExamAttempt).where(ExamAttempt.exam_id == exam.id, ExamAttempt.student_id == student.id))


def start_attempt(db: Session, exam: Exam, student: Student) -> ExamAttempt:
    attempt = get_attempt(db, exam, student)
    if attempt is None:
        attempt = ExamAttempt(exam_id=exam.id, student_id=student.id, started_at=utcnow(), answers={}, results={})
        db.add(attempt)
        db.flush()
    return attempt


def seconds_left(exam: Exam, attempt: ExamAttempt) -> int:
    elapsed = (utcnow() - attempt.started_at).total_seconds()
    return max(0, int(exam.duration_min * 60 - elapsed))


def submit_attempt(
    db: Session, ai: AIProvider, exam: Exam, attempt: ExamAttempt, answers: dict[str, str], use_ai: bool = True
) -> ExamAttempt:
    if attempt.submitted_at is not None:
        return attempt
    questions = exam_questions(db, exam)
    results: dict[str, bool] = {}
    clean: dict[str, str] = {}
    for q in questions:
        raw = (answers.get(str(q.id)) or "").strip()
        clean[str(q.id)] = raw
        ok = check_answer(ai, q, raw, use_ai=use_ai).correct if raw else False
        results[str(q.id)] = ok
        # Bài kiểm tra là bằng chứng về mức nắm vững (không tính "học được" trong lúc làm bài)
        apply_evidence(db, attempt.student_id, q.topic_id, 1.0 if ok else 0.0, q.kind, learn=False)
    attempt.answers = clean
    attempt.results = results
    attempt.total = len(questions)
    attempt.correct_count = sum(1 for v in results.values() if v)
    attempt.score = round(10 * attempt.correct_count / attempt.total, 2) if attempt.total else 0.0
    attempt.submitted_at = utcnow()
    return attempt


def auto_pick_questions(db: Session, course_id: int, per_topic: int, seed: int | None = None) -> list[int]:
    """Chọn ngẫu nhiên per_topic câu (dùng cho kiểm tra) ở mỗi chủ đề."""
    rng = random.Random(seed)
    picked: list[int] = []
    questions = db.scalars(
        select(Question).where(
            Question.course_id == course_id,
            Question.status == "approved",
            Question.purpose.in_(("test", "both")),
        )
    ).all()
    by_topic: dict[int, list[int]] = {}
    for q in questions:
        by_topic.setdefault(q.topic_id, []).append(q.id)
    for _topic_id, ids in sorted(by_topic.items()):
        rng.shuffle(ids)
        picked.extend(sorted(ids[:per_topic]))
    return picked
