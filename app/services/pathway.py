"""Lộ trình học cá nhân hóa và chọn câu luyện tập phù hợp.

- Chủ đề được đề xuất: chủ đề đầu tiên theo thứ tự chưa thành thạo và đã đạt các chủ đề tiên quyết.
- Câu luyện tập: độ khó bám theo mức nắm vững (thấp → Nhận biết, cao → Vận dụng cao); câu đã tự giải gần đây
  được hạ ưu tiên; câu từng phải nhờ nhiều gợi ý được đưa trở lại sau ít nhất 12 giờ (ôn lại giãn cách).
"""

from __future__ import annotations

import random
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PracticeSession, Question, Student, Topic
from ..utils.timeutil import utcnow, week_start_local
from .mastery import TopicState, get_mastery, topic_states


def target_difficulty(p: float) -> int:
    if p < 0.35:
        return 1
    if p < 0.6:
        return 2
    if p < 0.8:
        return 3
    return 4


def practice_questions(db: Session, topic: Topic) -> list[Question]:
    return list(
        db.scalars(
            select(Question)
            .where(
                Question.topic_id == topic.id,
                Question.status == "approved",
                Question.purpose.in_(("practice", "both")),
            )
            .order_by(Question.id)
        ).all()
    )


def active_session(db: Session, student: Student, topic_id: int | None = None) -> PracticeSession | None:
    stmt = select(PracticeSession).where(PracticeSession.student_id == student.id, PracticeSession.status == "active")
    if topic_id is not None:
        stmt = stmt.where(PracticeSession.topic_id == topic_id)
    return db.scalars(stmt.order_by(PracticeSession.id.desc())).first()


def pick_question(db: Session, student: Student, topic: Topic, rng: random.Random | None = None) -> Question | None:
    candidates = practice_questions(db, topic)
    if not candidates:
        return None
    rng = rng or random.Random()
    p = get_mastery(db, student.id, topic.id).p_known
    target = target_difficulty(p)
    last: dict[int, PracticeSession] = {}
    for s in db.scalars(
        select(PracticeSession)
        .where(PracticeSession.student_id == student.id, PracticeSession.topic_id == topic.id)
        .order_by(PracticeSession.id)
    ).all():
        last[s.question_id] = s
    now = utcnow()
    best: tuple[float, Question] | None = None
    for q in candidates:
        score = abs(q.difficulty - target)
        prev = last.get(q.id)
        if prev is None:
            score -= 0.3  # ưu tiên câu mới
        else:
            hours = (now - prev.started_at).total_seconds() / 3600
            if prev.independent:
                score += 3 if hours < 72 else 1
            elif hours < 12:
                score += 2  # vừa làm xong, chưa nên lặp lại ngay
            else:
                score -= 0.5  # từng cần nhiều hỗ trợ: ôn lại
        score += rng.random() * 0.2
        if best is None or score < best[0]:
            best = (score, q)
    return best[1] if best else None


def recommended(states: list[TopicState]) -> TopicState | None:
    for st in states:
        if st.status != "mastered" and not st.locked:
            return st
    for st in states:
        if st.status != "mastered":
            return st
    return min(states, key=lambda s: s.p) if states else None


def learning_path(db: Session, student: Student) -> tuple[list[TopicState], TopicState | None]:
    topics = student.classroom.course.topics
    states = topic_states(db, student, topics)
    return states, recommended(states)


def student_stats(db: Session, student: Student) -> dict:
    finished = [s for s in student.sessions if s.status != "active"]
    n = len(finished)
    weekly: dict[str, list[PracticeSession]] = defaultdict(list)
    for s in finished:
        weekly[week_start_local(s.started_at)].append(s)
    trend = []
    for week in sorted(weekly)[-8:]:
        items = weekly[week]
        trend.append(
            {
                "week": week,
                "n": len(items),
                "independent_rate": sum(1 for s in items if s.independent) / len(items),
                "mean_level": sum(s.max_hint_level for s in items) / len(items),
            }
        )
    return {
        "n": n,
        "solved": sum(1 for s in finished if s.correct),
        "independent": sum(1 for s in finished if s.independent),
        "independent_rate": (sum(1 for s in finished if s.independent) / n) if n else None,
        "mean_level": (sum(s.max_hint_level for s in finished) / n) if n else None,
        "solutions": sum(1 for s in finished if s.solution_viewed),
        "trend": trend,
    }
