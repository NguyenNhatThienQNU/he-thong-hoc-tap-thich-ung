"""Thực nghiệm so sánh: AI hỗ trợ thích ứng (nhóm thực nghiệm) và AI giải trực tiếp (nhóm đối chứng).

Ba nhóm chỉ số theo mục tiêu đề tài:
1. Khả năng ghi nhớ: điểm bài kiểm tra ghi nhớ (trì hoãn) và mức giảm so với bài ngay sau học.
2. Giải quyết bài tập độc lập: điểm bài kiểm tra không có AI; tỉ lệ câu luyện tập tự giải (tự lực).
3. Mức độ cần hỗ trợ từ AI: mức gợi ý cao nhất trung bình mỗi câu, số lần nhờ AI, tỉ lệ xem lời giải,
   và xu hướng theo tuần.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MODE_ADAPTIVE, MODE_DIRECT, Classroom, Course, Exam, ExamAttempt, PracticeSession, Student
from ..utils.text import vn_name_key
from ..utils.timeutil import week_start_local
from .stats import Comparison, compare, mean

GROUPS = (MODE_ADAPTIVE, MODE_DIRECT)


def course_students(db: Session, course: Course) -> list[Student]:
    return list(
        db.scalars(
            select(Student).join(Classroom, Student.classroom_id == Classroom.id).where(Classroom.course_id == course.id)
        ).all()
    )


def exam_scores(db: Session, course: Course, kind: str) -> dict[int, float]:
    """Điểm (thang 10) của mỗi học sinh ở bài kiểm tra loại kind; nhiều bài cùng loại thì lấy bài mới nhất."""
    exams = [e for e in course.exams if e.kind == kind]
    scores: dict[int, float] = {}
    for exam in sorted(exams, key=lambda e: e.id):
        for att in db.scalars(select(ExamAttempt).where(ExamAttempt.exam_id == exam.id)).all():
            if att.submitted_at is not None and att.score is not None:
                scores[att.student_id] = att.score
    return scores


@dataclass
class StudentRow:
    student: Student
    group: str
    pre: float | None = None
    post: float | None = None
    retention: float | None = None
    sessions: int = 0
    independent_rate: float | None = None
    mean_level: float | None = None
    mean_requests: float | None = None
    solution_rate: float | None = None

    @property
    def gain(self) -> float | None:
        if self.pre is None or self.post is None:
            return None
        return self.post - self.pre

    @property
    def retention_drop(self) -> float | None:
        if self.post is None or self.retention is None:
            return None
        return self.post - self.retention


def practice_summary(sessions: list[PracticeSession]) -> dict:
    done = [s for s in sessions if s.status != "active"]
    n = len(done)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "solved_rate": sum(1 for s in done if s.correct) / n,
        "independent_rate": sum(1 for s in done if s.independent) / n,
        "mean_level": sum(s.max_hint_level for s in done) / n,
        "mean_requests": sum(s.hint_requests for s in done) / n,
        "solution_rate": sum(1 for s in done if s.solution_viewed) / n,
    }


def student_rows(db: Session, course: Course, students: list[Student] | None = None) -> list[StudentRow]:
    students = students if students is not None else course_students(db, course)
    pre = exam_scores(db, course, "pre")
    post = exam_scores(db, course, "post")
    ret = exam_scores(db, course, "retention")
    rows = []
    for st in students:
        summary = practice_summary(st.sessions)
        rows.append(
            StudentRow(
                student=st,
                group=st.effective_mode,
                pre=pre.get(st.id),
                post=post.get(st.id),
                retention=ret.get(st.id),
                sessions=summary["n"],
                independent_rate=summary.get("independent_rate"),
                mean_level=summary.get("mean_level"),
                mean_requests=summary.get("mean_requests"),
                solution_rate=summary.get("solution_rate"),
            )
        )
    rows.sort(key=lambda r: (r.student.classroom.name, vn_name_key(r.student.full_name)))
    return rows


METRICS = [
    ("pre", "Điểm bài đầu vào", "điểm", "Kiểm tra hai nhóm tương đương trước thực nghiệm"),
    ("post", "Điểm bài ngay sau học (không AI)", "điểm", "Khả năng giải bài độc lập"),
    ("retention", "Điểm bài ghi nhớ (trì hoãn, không AI)", "điểm", "Khả năng ghi nhớ"),
    ("gain", "Mức tiến bộ (sau học − đầu vào)", "điểm", "Hiệu quả học tập"),
    ("retention_drop", "Mức giảm sau thời gian trì hoãn", "điểm", "Càng nhỏ càng nhớ lâu"),
    ("independent_rate", "Tỉ lệ câu luyện tập tự giải", "%", "Giải quyết bài tập độc lập"),
    ("mean_level", "Mức hỗ trợ trung bình mỗi câu (0–5)", "mức", "Mức độ cần hỗ trợ từ AI"),
    ("mean_requests", "Số lần nhờ AI trung bình mỗi câu", "lần", "Mức độ cần hỗ trợ từ AI"),
    ("solution_rate", "Tỉ lệ câu phải xem lời giải", "%", "Mức độ phụ thuộc AI"),
]


@dataclass
class Report:
    rows: list[StudentRow]
    comparisons: list[tuple[tuple[str, str, str, str], Comparison]]
    practice: dict[str, dict]
    trend: dict[str, list[dict]]
    weeks: list[str]
    has_demo: bool
    group_sizes: dict[str, int] = field(default_factory=dict)


def build_report(db: Session, course: Course) -> Report:
    rows = student_rows(db, course)
    comparisons = []
    for metric in METRICS:
        key = metric[0]
        a = [getattr(r, key) for r in rows if r.group == MODE_ADAPTIVE and getattr(r, key) is not None]
        b = [getattr(r, key) for r in rows if r.group == MODE_DIRECT and getattr(r, key) is not None]
        comparisons.append((metric, compare(a, b)))
    sessions_by_group: dict[str, list[PracticeSession]] = defaultdict(list)
    for r in rows:
        sessions_by_group[r.group].extend(r.student.sessions)
    practice = {g: practice_summary(sessions_by_group[g]) for g in GROUPS}
    # Xu hướng theo tuần: mức hỗ trợ trung bình và tỉ lệ tự giải của từng nhóm
    weekly: dict[str, dict[str, list[PracticeSession]]] = {g: defaultdict(list) for g in GROUPS}
    for g in GROUPS:
        for s in sessions_by_group[g]:
            if s.status != "active":
                weekly[g][week_start_local(s.started_at)].append(s)
    weeks = sorted({w for g in GROUPS for w in weekly[g]})
    trend = {
        g: [
            {
                "week": w,
                "n": len(weekly[g].get(w, [])),
                "mean_level": mean([s.max_hint_level for s in weekly[g].get(w, [])]),
                "independent_rate": mean([1.0 if s.independent else 0.0 for s in weekly[g].get(w, [])]),
            }
            for w in weeks
        ]
        for g in GROUPS
    }
    return Report(
        rows=rows,
        comparisons=comparisons,
        practice=practice,
        trend=trend,
        weeks=weeks,
        has_demo=any(r.student.is_demo for r in rows),
        group_sizes={g: sum(1 for r in rows if r.group == g) for g in GROUPS},
    )


def balanced_assignment(db: Session, classroom: Classroom, seed: int | None = None) -> dict[str, int]:
    """Chia ngẫu nhiên hai nhóm cân bằng theo điểm đầu vào: xếp theo điểm, ghép cặp liền kề,
    trong mỗi cặp bốc thăm một em vào nhóm thực nghiệm, một em vào nhóm đối chứng."""
    rng = random.Random(seed)
    course = classroom.course
    pre = exam_scores(db, course, "pre")
    students = list(classroom.students)
    rng.shuffle(students)  # học sinh chưa có điểm được xếp ngẫu nhiên ở cuối
    students.sort(key=lambda s: (pre.get(s.id) is None, -(pre.get(s.id) or 0)))
    counts = {MODE_ADAPTIVE: 0, MODE_DIRECT: 0}
    for i in range(0, len(students), 2):
        pair = students[i : i + 2]
        groups = [MODE_ADAPTIVE, MODE_DIRECT]
        rng.shuffle(groups)
        if len(pair) == 1:  # em lẻ cuối cùng: vào nhóm đang ít hơn
            groups = [min(counts, key=lambda g: (counts[g], rng.random()))]
        for student, group in zip(pair, groups, strict=False):
            student.mode = group
            counts[group] += 1
    return counts


def exam_kind_counts(course: Course) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for exam in course.exams:
        out[exam.kind] += 1
    return out


def exams_by_kind(course: Course, kind: str) -> list[Exam]:
    return [e for e in course.exams if e.kind == kind]
