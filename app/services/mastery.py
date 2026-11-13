"""Mức nắm vững theo chủ đề – Bayesian Knowledge Tracing (BKT) có trọng số theo mức hỗ trợ.

Mỗi học sinh có xác suất p = P(đã nắm vững chủ đề). Sau mỗi bằng chứng (một câu luyện tập
hoặc một câu trong bài kiểm tra), p được cập nhật theo công thức Bayes:

    P(L | đúng) = p(1 − s) / [p(1 − s) + (1 − p)g]
    P(L | sai)  = p·s / [p·s + (1 − p)(1 − g)]

trong đó s (slip) là xác suất nắm vững nhưng vẫn làm sai, g (guess) là xác suất đoán đúng.
Với luyện tập có AI hỗ trợ, một câu làm đúng nhờ nhiều gợi ý không chứng minh được học sinh
đã nắm vững. Vì vậy hệ thống dùng "điểm tín nhiệm" c ∈ [0, 1]:

    p_hậu nghiệm = c · P(L | đúng) + (1 − c) · P(L | sai)
    p_mới = p_hậu nghiệm + (1 − p_hậu nghiệm) · T      (T: xác suất học được sau một lần luyện)
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Mastery, PracticeSession, Student, Topic
from ..utils.timeutil import utcnow

P_INIT = 0.3
P_TRANSIT = 0.12
P_SLIP = 0.10
GUESS = {"mcq": 0.25, "short": 0.08, "open": 0.10}

MASTERED = 0.85  # từ ngưỡng này coi là thành thạo
SOLID = 0.7  # nắm khá chắc – bắt đầu giảm hỗ trợ
WEAK = 0.4  # dưới ngưỡng này là còn yếu


def posterior(p: float, correct: bool, guess: float, slip: float = P_SLIP) -> float:
    if correct:
        num = p * (1 - slip)
        den = num + (1 - p) * guess
    else:
        num = p * slip
        den = num + (1 - p) * (1 - guess)
    return num / den if den > 0 else p


def bkt_update(p: float, credit: float, kind: str = "short", learn: bool = True) -> float:
    """Cập nhật p với điểm tín nhiệm credit (1 = đúng hoàn toàn tự lực, 0 = sai)."""
    credit = min(1.0, max(0.0, credit))
    guess = GUESS.get(kind, 0.1)
    post = credit * posterior(p, True, guess) + (1 - credit) * posterior(p, False, guess)
    if learn:
        post = post + (1 - post) * P_TRANSIT
    return round(min(0.99, max(0.05, post)), 4)


def session_credit(session: PracticeSession, kind: str) -> float:
    """Điểm tín nhiệm của một phiên luyện tập.

    - Đúng ngay lần đầu, không gợi ý: 1,0
    - Mỗi lần trả lời sai trước đó: −0,2 (trắc nghiệm −0,3 vì có thể đoán mò)
    - Gợi ý mức 1 (chỉ là câu hỏi định hướng): −0,05; từ mức 2 trở lên: thêm −0,2 cho mỗi mức
    - Xem lời giải hoặc bỏ qua: 0
    """
    if not session.correct or session.solution_viewed:
        return 0.0
    wrong_penalty = 0.3 if kind == "mcq" else 0.2
    credit = 1.0 - wrong_penalty * session.wrong_attempts
    level = session.max_hint_level
    if level == 1:
        credit -= 0.05
    elif level >= 2:
        credit -= 0.05 + 0.2 * (level - 1)
    return round(max(0.05, credit), 3)


def get_mastery(db: Session, student_id: int, topic_id: int, create: bool = True) -> Mastery | None:
    m = db.scalar(select(Mastery).where(Mastery.student_id == student_id, Mastery.topic_id == topic_id))
    if m is None and create:
        m = Mastery(student_id=student_id, topic_id=topic_id, p_known=P_INIT, n_obs=0, updated_at=utcnow())
        db.add(m)
        db.flush()
    return m


def mastery_map(db: Session, student: Student) -> dict[int, Mastery]:
    rows = db.scalars(select(Mastery).where(Mastery.student_id == student.id)).all()
    return {m.topic_id: m for m in rows}


def apply_evidence(
    db: Session, student_id: int, topic_id: int, credit: float, kind: str, learn: bool = True
) -> tuple[float, float]:
    m = get_mastery(db, student_id, topic_id)
    before = m.p_known
    m.p_known = bkt_update(before, credit, kind, learn=learn)
    m.n_obs += 1
    m.updated_at = utcnow()
    return before, m.p_known


@dataclass
class TopicState:
    topic: Topic
    p: float
    n_obs: int
    status: str  # mastered | learning | weak | new
    locked: bool  # chưa đạt chủ đề tiên quyết
    missing_prereqs: list[str]

    @property
    def pct(self) -> int:
        return round(self.p * 100)

    @property
    def label(self) -> str:
        return {
            "mastered": "Thành thạo",
            "learning": "Đang tiến bộ",
            "weak": "Cần củng cố",
            "new": "Chưa học",
        }[self.status]

    @property
    def css(self) -> str:
        return {"mastered": "success", "learning": "primary", "weak": "warning", "new": "secondary"}[self.status]


def classify(p: float, n_obs: int) -> str:
    if n_obs == 0:
        return "new"
    if p >= MASTERED:
        return "mastered"
    if p >= WEAK:
        return "learning"
    return "weak"


def topic_states(db: Session, student: Student, topics: list[Topic]) -> list[TopicState]:
    mm = mastery_map(db, student)
    by_id = {t.id: t for t in topics}
    states: list[TopicState] = []
    for t in topics:
        m = mm.get(t.id)
        p = m.p_known if m else P_INIT
        n = m.n_obs if m else 0
        missing = []
        for pid in t.prerequisite_ids or []:
            pm = mm.get(pid)
            if pid in by_id and (pm is None or pm.p_known < 0.6):
                missing.append(by_id[pid].name)
        states.append(TopicState(t, p, n, classify(p, n), bool(missing), missing))
    return states
