"""Bài kiểm tra không có AI: đầu vào, ngay sau học, ghi nhớ (trì hoãn)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EXAM_KINDS, Exam, ExamAttempt, Teacher
from ..services.assessment import auto_pick_questions, exam_questions
from ..services.experiment import course_students
from ..services.stats import mean
from ..utils.text import vn_name_key
from .deps import (
    current_teacher,
    flash,
    form_int,
    get_db,
    owned_course,
    owned_exam,
    owned_student,
    redirect,
    render,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


def _attempts(db: Session, exam: Exam) -> list[ExamAttempt]:
    return list(db.scalars(select(ExamAttempt).where(ExamAttempt.exam_id == exam.id)).all())


@router.get("/mon-hoc/{course_id}/kiem-tra")
def exam_list(course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    course = owned_course(db, teacher, course_id)
    rows = []
    for exam in course.exams:
        done = [a for a in _attempts(db, exam) if a.submitted_at is not None]
        rows.append((exam, len(done), mean([a.score for a in done if a.score is not None])))
    test_pool = sum(1 for q in course.questions if q.status == "approved" and q.for_test)
    return render(
        request,
        "course/exams.html",
        teacher=teacher,
        active="courses",
        tab="exams",
        course=course,
        rows=rows,
        test_pool=test_pool,
    )


@router.post("/mon-hoc/{course_id}/kiem-tra")
def exam_create(
    course_id: int,
    request: Request,
    title: str = Form(...),
    kind: str = Form("other"),
    duration_min: int = Form(20),
    per_topic: int = Form(2),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    ids = auto_pick_questions(db, course.id, max(0, min(10, per_topic))) if per_topic > 0 else []
    exam = Exam(
        course_id=course.id,
        title=" ".join(title.split()) or "Bài kiểm tra",
        kind=kind if kind in EXAM_KINDS else "other",
        duration_min=max(1, min(180, duration_min)),
        question_ids=ids,
        is_open=False,
    )
    db.add(exam)
    db.commit()
    flash(request, f"Đã tạo bài kiểm tra với {len(ids)} câu. Kiểm tra lại danh sách câu rồi bấm “Mở cho học sinh làm”.")
    return redirect(f"/kiem-tra/{exam.id}")


@router.get("/kiem-tra/{exam_id}")
def exam_detail(exam_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    exam = owned_exam(db, teacher, exam_id)
    course = exam.course
    selected = [int(i) for i in exam.question_ids or []]
    pool = [q for q in course.questions if q.status == "approved" and (q.for_test or q.id in selected)]
    by_topic = []
    for t in course.topics:
        items = [q for q in pool if q.topic_id == t.id]
        if items:
            by_topic.append((t, items))
    attempts = {a.student_id: a for a in _attempts(db, exam)}
    students = course_students(db, course)
    students.sort(key=lambda s: (s.classroom.name, vn_name_key(s.full_name)))
    return render(
        request,
        "course/exam_detail.html",
        teacher=teacher,
        active="courses",
        tab="exams",
        course=course,
        exam=exam,
        selected=set(selected),
        by_topic=by_topic,
        questions=exam_questions(db, exam),
        students=students,
        attempts=attempts,
    )


@router.post("/kiem-tra/{exam_id}")
async def exam_update(exam_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    exam = owned_exam(db, teacher, exam_id)
    form = await request.form()
    title = " ".join(str(form.get("title") or "").split())
    if title:
        exam.title = title
    kind = str(form.get("kind") or exam.kind)
    exam.kind = kind if kind in EXAM_KINDS else exam.kind
    exam.duration_min = max(1, min(180, form_int(form.get("duration_min"), exam.duration_min)))
    exam.show_answers = form.get("show_answers") == "on"
    valid = {q.id for q in exam.course.questions}
    ids = []
    for raw in form.getlist("question_ids"):
        qid = form_int(raw)
        if qid in valid and qid not in ids:
            ids.append(qid)
    has_attempts = any(a.submitted_at for a in _attempts(db, exam))
    if has_attempts and ids != [int(i) for i in exam.question_ids or []]:
        flash(request, "Bài đã có học sinh nộp nên không đổi danh sách câu hỏi (để giữ tính so sánh). Các mục khác đã lưu.", "warning")
    else:
        exam.question_ids = ids
        flash(request, f"Đã lưu bài kiểm tra ({len(ids)} câu).")
    db.commit()
    return redirect(f"/kiem-tra/{exam.id}")


@router.post("/kiem-tra/{exam_id}/mo")
def exam_toggle(exam_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    exam = owned_exam(db, teacher, exam_id)
    if not exam.is_open and not exam.question_ids:
        flash(request, "Bài kiểm tra chưa có câu hỏi.", "danger")
        return redirect(f"/kiem-tra/{exam.id}")
    exam.is_open = not exam.is_open
    db.commit()
    flash(request, "Đã mở bài cho học sinh làm." if exam.is_open else "Đã đóng bài kiểm tra.")
    return redirect(f"/kiem-tra/{exam.id}")


@router.post("/kiem-tra/{exam_id}/xoa")
def exam_delete(exam_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    exam = owned_exam(db, teacher, exam_id)
    course_id = exam.course_id
    db.delete(exam)
    db.commit()
    flash(request, "Đã xóa bài kiểm tra và các bài làm liên quan.")
    return redirect(f"/mon-hoc/{course_id}/kiem-tra")


@router.post("/kiem-tra/{exam_id}/lam-lai/{student_id}")
def exam_reset(
    exam_id: int, student_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    exam = owned_exam(db, teacher, exam_id)
    student = owned_student(db, teacher, student_id)
    attempt = db.scalar(select(ExamAttempt).where(ExamAttempt.exam_id == exam.id, ExamAttempt.student_id == student.id))
    if attempt is not None:
        db.delete(attempt)
        db.commit()
        flash(request, f"Đã cho phép {student.full_name} làm lại bài.")
    return redirect(f"/kiem-tra/{exam.id}")
