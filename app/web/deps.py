"""Phụ thuộc dùng chung cho các route web: CSDL, đăng nhập, CSRF, giao diện, kiểm tra quyền sở hữu."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import SessionLocal
from ..models import (
    DIFFICULTY,
    DIFFICULTY_TYPES,
    EXAM_KINDS,
    HINT_LEVELS,
    MATERIAL_STATUS,
    MODE_GROUPS,
    MODE_LABELS,
    PURPOSES,
    QUESTION_KINDS,
    QUESTION_STATUS,
    Classroom,
    Course,
    Exam,
    Material,
    PracticeSession,
    Question,
    Student,
    Teacher,
    Topic,
)
from ..security import new_csrf_token, tokens_match
from ..utils.md import render_md
from ..utils.text import OPTION_LETTERS, fmt_pct, fmt_score, truncate
from ..utils.timeutil import fmt_local, humanize_ago, utcnow

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _nl2br(text: str | None) -> Markup:
    return Markup("<br>".join(escape(text or "").split("\n")))


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:.3f}".replace(".", ",") if value >= 0.001 else "< 0,001"


templates.env.filters.update(
    localdt=fmt_local,
    score=fmt_score,
    pct=fmt_pct,
    pval=_fmt_p,
    truncate_text=truncate,
    nl2br=_nl2br,
    md=render_md,
    ago=humanize_ago,
    tojson_vn=lambda v: Markup(json.dumps(v, ensure_ascii=False)),
)
templates.env.globals.update(
    DIFFICULTY=DIFFICULTY,
    DIFFICULTY_TYPES=DIFFICULTY_TYPES,
    EXAM_KINDS=EXAM_KINDS,
    HINT_LEVELS=HINT_LEVELS,
    MATERIAL_STATUS=MATERIAL_STATUS,
    MODE_GROUPS=MODE_GROUPS,
    MODE_LABELS=MODE_LABELS,
    PURPOSES=PURPOSES,
    QUESTION_KINDS=QUESTION_KINDS,
    QUESTION_STATUS=QUESTION_STATUS,
    LETTERS=OPTION_LETTERS,
)


class LoginRequired(Exception):
    """Giáo viên chưa đăng nhập – chuyển tới trang đăng nhập."""


class StudentLoginRequired(Exception):
    """Học sinh chưa đăng nhập – chuyển tới trang nhập mã."""


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_teacher(request: Request, db: Session = Depends(get_db)) -> Teacher:
    teacher_id = request.session.get("teacher_id")
    teacher = db.get(Teacher, teacher_id) if teacher_id else None
    if teacher is None:
        raise LoginRequired()
    return teacher


def current_student(request: Request, db: Session = Depends(get_db)) -> Student:
    student_id = request.session.get("student_id")
    student = db.get(Student, student_id) if student_id else None
    if student is None:
        raise StudentLoginRequired()
    now = utcnow()
    if student.last_seen_at is None or (now - student.last_seen_at).total_seconds() > 300:
        student.last_seen_at = now
        db.commit()
    return student


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = new_csrf_token()
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    sent = request.headers.get("x-csrf-token")
    if not sent:
        form = await request.form()
        sent = form.get("csrf_token")
    if not tokens_match(sent, request.session.get("csrf")):
        raise HTTPException(status_code=403, detail="Phiên làm việc đã hết hạn. Hãy tải lại trang rồi thử lại.")


def flash(request: Request, message: str, category: str = "success") -> None:
    flashes = request.session.get("_flashes", [])
    flashes.append([category, message])
    request.session["_flashes"] = flashes


def pop_flashes(request: Request) -> list:
    return request.session.pop("_flashes", [])


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def public_url(request: Request) -> str:
    """Địa chỉ gốc học sinh dùng để vào web (in trên mã QR).

    Nếu chưa đặt PUBLIC_BASE_URL (vẫn là localhost) thì lấy theo tên miền đang truy cập,
    ví dụ https://ten-du-an.vercel.app khi chạy trên Vercel.
    """
    configured = request.app.state.settings.public_base_url.rstrip("/")
    if "localhost" not in configured and "127.0.0.1" not in configured:
        return configured
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if not host or host.startswith(("localhost", "127.0.0.1")):
        return configured
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{proto}://{host}"


def render(request: Request, name: str, *, status_code: int = 200, **context):
    settings: Settings = request.app.state.settings
    context.setdefault("teacher", None)
    context.setdefault("student", None)
    context.setdefault("active", "")
    context.update(
        app_name=settings.app_name,
        ai_demo=not request.app.state.ai.is_real,
        ephemeral_db=settings.uses_ephemeral_db,
        flashes=pop_flashes(request),
        csrf_token=csrf_token(request),
    )
    return templates.TemplateResponse(request, name, context, status_code=status_code)


# ---------------------------------------------------------------------------
# Lấy bản ghi kèm kiểm tra quyền sở hữu (giáo viên chỉ thấy dữ liệu của mình)
# ---------------------------------------------------------------------------


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Không tìm thấy dữ liệu.")


def owned_course(db: Session, teacher: Teacher, course_id: int) -> Course:
    obj = db.get(Course, course_id)
    if obj is None or obj.teacher_id != teacher.id:
        raise not_found()
    return obj


def owned_topic(db: Session, teacher: Teacher, topic_id: int) -> Topic:
    obj = db.get(Topic, topic_id)
    if obj is None or obj.course.teacher_id != teacher.id:
        raise not_found()
    return obj


def owned_material(db: Session, teacher: Teacher, material_id: int) -> Material:
    obj = db.get(Material, material_id)
    if obj is None or obj.course.teacher_id != teacher.id:
        raise not_found()
    return obj


def owned_question(db: Session, teacher: Teacher, question_id: int) -> Question:
    obj = db.get(Question, question_id)
    if obj is None or obj.course.teacher_id != teacher.id:
        raise not_found()
    return obj


def owned_exam(db: Session, teacher: Teacher, exam_id: int) -> Exam:
    obj = db.get(Exam, exam_id)
    if obj is None or obj.course.teacher_id != teacher.id:
        raise not_found()
    return obj


def owned_classroom(db: Session, teacher: Teacher, class_id: int) -> Classroom:
    obj = db.get(Classroom, class_id)
    if obj is None or obj.teacher_id != teacher.id:
        raise not_found()
    return obj


def owned_student(db: Session, teacher: Teacher, student_id: int) -> Student:
    obj = db.get(Student, student_id)
    if obj is None or obj.classroom.teacher_id != teacher.id:
        raise not_found()
    return obj


def owned_session(db: Session, teacher: Teacher, session_id: int) -> PracticeSession:
    obj = db.get(PracticeSession, session_id)
    if obj is None or obj.student.classroom.teacher_id != teacher.id:
        raise not_found()
    return obj


def teacher_courses(db: Session, teacher: Teacher) -> list[Course]:
    return list(db.scalars(select(Course).where(Course.teacher_id == teacher.id).order_by(Course.id)).all())


def teacher_classes(db: Session, teacher: Teacher) -> list[Classroom]:
    return list(db.scalars(select(Classroom).where(Classroom.teacher_id == teacher.id).order_by(Classroom.name)).all())


def form_int(value, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
