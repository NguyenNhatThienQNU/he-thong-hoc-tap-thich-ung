"""Môn học, chủ đề (lộ trình) và chính sách gợi ý."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DEFAULT_POLICY, Course, PracticeSession, Question, Teacher, Topic
from .deps import (
    current_teacher,
    flash,
    form_int,
    get_db,
    owned_course,
    owned_topic,
    redirect,
    render,
    teacher_courses,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


def course_counts(db: Session, course: Course) -> dict:
    qs = course.questions
    return {
        "topics": len(course.topics),
        "materials": len(course.materials),
        "materials_pending": sum(1 for m in course.materials if not m.is_approved),
        "questions": sum(1 for q in qs if q.status == "approved"),
        "drafts": sum(1 for q in qs if q.status == "draft"),
        "exams": len(course.exams),
        "classes": len(course.classes),
        "students": sum(len(c.students) for c in course.classes),
    }


@router.get("/mon-hoc")
def course_list(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    courses = teacher_courses(db, teacher)
    return render(
        request,
        "course/list.html",
        teacher=teacher,
        active="courses",
        courses=[(c, course_counts(db, c)) for c in courses],
    )


@router.post("/mon-hoc")
def course_create(
    request: Request,
    name: str = Form(...),
    grade: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    name = " ".join(name.split())
    if not name:
        flash(request, "Vui lòng nhập tên môn học.", "danger")
        return redirect("/mon-hoc")
    course = Course(teacher_id=teacher.id, name=name, grade=grade.strip(), description=description.strip(), policy={})
    db.add(course)
    db.commit()
    flash(request, f"Đã tạo môn “{course.name}”. Bước tiếp theo: thêm các chủ đề theo thứ tự học.")
    return redirect(f"/mon-hoc/{course.id}")


@router.get("/mon-hoc/{course_id}")
def course_detail(
    course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    course = owned_course(db, teacher, course_id)
    topic_stats = {}
    for t in course.topics:
        topic_stats[t.id] = {
            "questions": sum(1 for q in t.questions if q.status == "approved"),
            "practice": sum(1 for q in t.questions if q.status == "approved" and q.for_practice),
            "test": sum(1 for q in t.questions if q.status == "approved" and q.for_test),
            "materials": sum(1 for m in t.materials if m.is_approved),
        }
    names = {t.id: t.name for t in course.topics}
    return render(
        request,
        "course/detail.html",
        teacher=teacher,
        active="courses",
        tab="topics",
        course=course,
        counts=course_counts(db, course),
        topic_stats=topic_stats,
        topic_names=names,
        policy=course.full_policy,
    )


@router.post("/mon-hoc/{course_id}/sua")
def course_update(
    course_id: int,
    request: Request,
    name: str = Form(...),
    grade: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    if " ".join(name.split()):
        course.name = " ".join(name.split())
    course.grade = grade.strip()
    course.description = description.strip()
    db.commit()
    flash(request, "Đã lưu thông tin môn học.")
    return redirect(f"/mon-hoc/{course.id}")


@router.post("/mon-hoc/{course_id}/xoa")
def course_delete(
    course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    course = owned_course(db, teacher, course_id)
    if course.classes:
        flash(request, "Không xóa được: môn học đang gắn với lớp. Hãy xóa hoặc chuyển lớp trước.", "danger")
        return redirect(f"/mon-hoc/{course.id}")
    db.delete(course)
    db.commit()
    flash(request, "Đã xóa môn học.")
    return redirect("/mon-hoc")


@router.post("/mon-hoc/{course_id}/chinh-sach")
async def course_policy(
    course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    course = owned_course(db, teacher, course_id)
    form = await request.form()
    policy = {
        "require_attempt_first": form.get("require_attempt_first") == "on",
        "fading": form.get("fading") == "on",
        "min_attempts_for_solution": max(0, min(5, form_int(form.get("min_attempts_for_solution"), 2))),
        "max_level_mastered": max(1, min(4, form_int(form.get("max_level_mastered"), 3))),
    }
    course.policy = {k: policy.get(k, v) for k, v in DEFAULT_POLICY.items()}
    db.commit()
    flash(request, "Đã lưu chính sách gợi ý. Thay đổi áp dụng cho các câu hỏi học sinh nhờ gợi ý từ bây giờ.")
    return redirect(f"/mon-hoc/{course.id}#chinh-sach")


def _prereq_ids(form, course: Course, exclude: int | None = None) -> list[int]:
    valid = {t.id for t in course.topics}
    ids = []
    for raw in form.getlist("prerequisites"):
        tid = form_int(raw)
        if tid in valid and tid != exclude and tid not in ids:
            ids.append(tid)
    return ids


@router.post("/mon-hoc/{course_id}/chu-de")
async def topic_create(
    course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    course = owned_course(db, teacher, course_id)
    form = await request.form()
    name = " ".join(str(form.get("name") or "").split())
    if not name:
        flash(request, "Vui lòng nhập tên chủ đề.", "danger")
        return redirect(f"/mon-hoc/{course.id}")
    position = form_int(form.get("position"))
    if position is None:
        position = (max((t.position for t in course.topics), default=0)) + 1
    topic = Topic(
        course_id=course.id,
        name=name,
        description=str(form.get("description") or "").strip(),
        position=position,
        prerequisite_ids=_prereq_ids(form, course),
    )
    db.add(topic)
    db.commit()
    flash(request, f"Đã thêm chủ đề “{topic.name}”.")
    return redirect(f"/mon-hoc/{course.id}")


@router.post("/chu-de/{topic_id}/sua")
async def topic_update(
    topic_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    topic = owned_topic(db, teacher, topic_id)
    form = await request.form()
    name = " ".join(str(form.get("name") or "").split())
    if name:
        topic.name = name
    topic.description = str(form.get("description") or "").strip()
    position = form_int(form.get("position"))
    if position is not None:
        topic.position = position
    topic.prerequisite_ids = _prereq_ids(form, topic.course, exclude=topic.id)
    db.commit()
    flash(request, "Đã cập nhật chủ đề.")
    return redirect(f"/mon-hoc/{topic.course_id}")


@router.post("/chu-de/{topic_id}/xoa")
def topic_delete(
    topic_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    topic = owned_topic(db, teacher, topic_id)
    course_id = topic.course_id
    n_questions = db.scalar(select(func.count(Question.id)).where(Question.topic_id == topic.id)) or 0
    n_sessions = db.scalar(select(func.count(PracticeSession.id)).where(PracticeSession.topic_id == topic.id)) or 0
    if n_questions or n_sessions:
        flash(request, "Không xóa được: chủ đề đã có câu hỏi hoặc dữ liệu luyện tập.", "danger")
        return redirect(f"/mon-hoc/{course_id}")
    for other in topic.course.topics:
        if topic.id in (other.prerequisite_ids or []):
            other.prerequisite_ids = [i for i in other.prerequisite_ids if i != topic.id]
    db.delete(topic)
    db.commit()
    flash(request, "Đã xóa chủ đề.")
    return redirect(f"/mon-hoc/{course_id}")
