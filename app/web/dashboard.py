"""Trang tổng quan của giáo viên, cài đặt và nạp dữ liệu mẫu."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Classroom, PracticeSession, Student, Teacher
from ..services.experiment import practice_summary
from ..utils.timeutil import utcnow
from .deps import (
    current_teacher,
    flash,
    get_db,
    public_url,
    redirect,
    render,
    teacher_classes,
    teacher_courses,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


def _teacher_sessions(db: Session, teacher: Teacher, since=None, limit: int | None = None) -> list[PracticeSession]:
    stmt = (
        select(PracticeSession)
        .join(Student, PracticeSession.student_id == Student.id)
        .join(Classroom, Student.classroom_id == Classroom.id)
        .where(Classroom.teacher_id == teacher.id)
        .order_by(PracticeSession.started_at.desc())
    )
    if since is not None:
        stmt = stmt.where(PracticeSession.started_at >= since)
    if limit:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    courses = teacher_courses(db, teacher)
    classes = teacher_classes(db, teacher)
    n_students = sum(len(c.students) for c in classes)
    week = _teacher_sessions(db, teacher, since=utcnow() - timedelta(days=7))
    summary = practice_summary(week)
    recent = _teacher_sessions(db, teacher, limit=8)
    # Học sinh cần chú ý: phụ thuộc gợi ý nhiều trong 14 ngày gần đây
    watch = []
    since = utcnow() - timedelta(days=14)
    for c in classes:
        for st in c.students:
            items = [s for s in st.sessions if s.started_at >= since and s.status != "active"]
            if len(items) < 3:
                continue
            info = practice_summary(items)
            if info["mean_level"] >= 3 or info["solution_rate"] >= 0.4:
                watch.append((st, info))
    watch.sort(key=lambda x: -x[1]["mean_level"])
    return render(
        request,
        "teacher/dashboard.html",
        teacher=teacher,
        active="dashboard",
        courses=courses,
        classes=classes,
        n_students=n_students,
        summary=summary,
        recent=recent,
        watch=watch[:8],
    )


@router.get("/cai-dat")
def settings_page(request: Request, teacher: Teacher = Depends(current_teacher)):
    settings = request.app.state.settings
    ai = request.app.state.ai
    return render(
        request,
        "teacher/settings.html",
        teacher=teacher,
        active="settings",
        ai_name=ai.name,
        ai_real=ai.is_real,
        model=settings.gemini_model,
        provider_setting=settings.ai_provider,
        public_url=public_url(request),
    )


@router.post("/demo/seed")
def seed_demo(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    from ..seed import seed_demo_data

    course, classroom = seed_demo_data(db, teacher)
    db.commit()
    flash(
        request,
        f"Đã nạp dữ liệu mẫu: môn “{course.name}”, lớp “{classroom.name}” với lịch sử luyện tập mô phỏng 3 tuần. "
        "Đây là dữ liệu mô phỏng để xem thử giao diện, không phải kết quả thực nghiệm.",
    )
    return redirect("/dashboard")
