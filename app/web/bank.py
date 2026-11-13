"""Ngân hàng câu hỏi: soạn tay, AI soạn nháp từ tài liệu đã duyệt, giáo viên duyệt."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.base import AIError
from ..ai.schemas import QuestionGenRequest
from ..models import DIFFICULTY, PURPOSES, QUESTION_KINDS, Course, Material, PracticeSession, Question, Teacher
from .deps import (
    current_teacher,
    flash,
    form_int,
    get_db,
    owned_course,
    owned_material,
    owned_question,
    redirect,
    render,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


def _usage(db: Session, question: Question) -> int:
    return db.scalar(select(func.count(PracticeSession.id)).where(PracticeSession.question_id == question.id)) or 0


def _in_exams(question: Question) -> list[str]:
    return [e.title for e in question.course.exams if question.id in [int(i) for i in e.question_ids or []]]


@router.get("/mon-hoc/{course_id}/cau-hoi")
def bank_list(
    course_id: int,
    request: Request,
    topic: int | None = None,
    status: str = "",
    purpose: str = "",
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    questions = list(course.questions)
    if topic:
        questions = [q for q in questions if q.topic_id == topic]
    if status:
        questions = [q for q in questions if q.status == status]
    else:
        questions = [q for q in questions if q.status != "archived"]
    if purpose:
        questions = [q for q in questions if q.purpose == purpose or (purpose != "both" and q.purpose == "both")]
    order = {t.id: i for i, t in enumerate(course.topics)}
    questions.sort(key=lambda q: (q.status != "draft", order.get(q.topic_id, 99), q.difficulty, q.id))
    approved_materials = [m for m in course.materials if m.is_approved]
    return render(
        request,
        "course/bank.html",
        teacher=teacher,
        active="courses",
        tab="bank",
        course=course,
        questions=questions,
        f_topic=topic,
        f_status=status,
        f_purpose=purpose,
        drafts=sum(1 for q in course.questions if q.status == "draft"),
        approved_materials=approved_materials,
        preselect_material=form_int(request.query_params.get("tai_lieu")),
    )


def _question_form_ctx(course: Course, question: Question | None) -> dict:
    return {"course": course, "question": question, "kinds": QUESTION_KINDS, "levels": DIFFICULTY, "purposes": PURPOSES}


@router.get("/mon-hoc/{course_id}/cau-hoi/moi")
def question_new(
    course_id: int,
    request: Request,
    topic: int | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    if not course.topics:
        flash(request, "Hãy tạo ít nhất một chủ đề trước khi soạn câu hỏi.", "warning")
        return redirect(f"/mon-hoc/{course.id}")
    return render(
        request,
        "course/question_form.html",
        teacher=teacher,
        active="courses",
        tab="bank",
        default_topic=topic,
        **_question_form_ctx(course, None),
    )


async def _apply_form(request: Request, course: Course, question: Question) -> list[str]:
    form = await request.form()
    errors = []
    topic_id = form_int(form.get("topic_id"))
    if topic_id not in {t.id for t in course.topics}:
        errors.append("Hãy chọn chủ đề.")
    kind = str(form.get("kind") or "short")
    if kind not in QUESTION_KINDS:
        kind = "short"
    stem = str(form.get("stem") or "").strip()
    if not stem:
        errors.append("Đề bài không được để trống.")
    options = [str(form.get(f"option_{i}") or "").strip() for i in range(6)]
    options = [o for o in options if o]
    correct = form_int(form.get("correct_option"))
    answer = str(form.get("answer") or "").strip()
    if kind == "mcq":
        if len(options) < 2:
            errors.append("Câu trắc nghiệm cần ít nhất 2 phương án.")
        if correct is None or not (0 <= correct < len(options)):
            errors.append("Hãy chọn phương án đúng.")
    elif not answer:
        errors.append("Hãy nhập đáp án (mỗi cách viết đúng một dòng).")
    question.topic_id = topic_id or question.topic_id
    question.kind = kind
    question.stem = stem
    question.options = options if kind == "mcq" else []
    question.correct_option = correct if kind == "mcq" else None
    question.answer = answer if kind != "mcq" else ""
    question.solution = str(form.get("solution") or "").strip()
    question.difficulty = max(1, min(4, form_int(form.get("difficulty"), 2)))
    purpose = str(form.get("purpose") or "practice")
    question.purpose = purpose if purpose in PURPOSES else "practice"
    status = str(form.get("status") or "approved")
    question.status = status if status in ("draft", "approved", "archived") else "approved"
    return errors


@router.post("/mon-hoc/{course_id}/cau-hoi")
async def question_create(
    course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    course = owned_course(db, teacher, course_id)
    question = Question(course_id=course.id, stem="", source="teacher")
    errors = await _apply_form(request, course, question)
    if errors:
        return render(
            request,
            "course/question_form.html",
            teacher=teacher,
            active="courses",
            tab="bank",
            errors=errors,
            status_code=400,
            **_question_form_ctx(course, question),
        )
    db.add(question)
    db.commit()
    flash(request, "Đã lưu câu hỏi.")
    if (await request.form()).get("again"):
        return redirect(f"/mon-hoc/{course.id}/cau-hoi/moi?topic={question.topic_id}")
    return redirect(f"/mon-hoc/{course.id}/cau-hoi")


@router.get("/cau-hoi/{question_id}")
def question_edit(
    question_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    question = owned_question(db, teacher, question_id)
    return render(
        request,
        "course/question_form.html",
        teacher=teacher,
        active="courses",
        tab="bank",
        usage=_usage(db, question),
        in_exams=_in_exams(question),
        **_question_form_ctx(question.course, question),
    )


@router.post("/cau-hoi/{question_id}")
async def question_update(
    question_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    question = owned_question(db, teacher, question_id)
    errors = await _apply_form(request, question.course, question)
    if errors:
        db.rollback()
        question = owned_question(db, teacher, question_id)
        return render(
            request,
            "course/question_form.html",
            teacher=teacher,
            active="courses",
            tab="bank",
            errors=errors,
            status_code=400,
            **_question_form_ctx(question.course, question),
        )
    db.commit()
    flash(request, "Đã cập nhật câu hỏi.")
    return redirect(f"/mon-hoc/{question.course_id}/cau-hoi")


@router.post("/cau-hoi/{question_id}/trang-thai")
def question_status(
    question_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    question = owned_question(db, teacher, question_id)
    if status in ("draft", "approved", "archived"):
        question.status = status
        db.commit()
        flash(request, {"approved": "Đã duyệt câu hỏi.", "archived": "Đã ẩn câu hỏi.", "draft": "Đã chuyển về nháp."}[status])
    return redirect(request.headers.get("referer") or f"/mon-hoc/{question.course_id}/cau-hoi")


@router.post("/cau-hoi/{question_id}/xoa")
def question_delete(
    question_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    question = owned_question(db, teacher, question_id)
    course_id = question.course_id
    if _usage(db, question) or _in_exams(question):
        question.status = "archived"
        flash(request, "Câu hỏi đã có dữ liệu luyện tập hoặc nằm trong bài kiểm tra nên được ẩn thay vì xóa.", "warning")
    else:
        db.delete(question)
        flash(request, "Đã xóa câu hỏi.")
    db.commit()
    return redirect(f"/mon-hoc/{course_id}/cau-hoi")


@router.post("/mon-hoc/{course_id}/cau-hoi/duyet")
async def bulk_approve(
    course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    course = owned_course(db, teacher, course_id)
    form = await request.form()
    ids = {form_int(i) for i in form.getlist("ids")}
    n = 0
    for q in course.questions:
        if q.id in ids and q.status == "draft":
            q.status = "approved"
            n += 1
    db.commit()
    flash(request, f"Đã duyệt {n} câu hỏi.")
    return redirect(f"/mon-hoc/{course.id}/cau-hoi")


@router.post("/mon-hoc/{course_id}/cau-hoi/ai")
def ai_generate(
    course_id: int,
    request: Request,
    material_id: str = Form(""),
    topic_id: str = Form(""),
    count: int = Form(5),
    difficulty: int = Form(2),
    kind: str = Form("mixed"),
    purpose: str = Form("practice"),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    mid = form_int(material_id)
    tid = form_int(topic_id)
    material: Material | None = owned_material(db, teacher, mid) if mid else None
    if material is not None and material.course_id != course.id:
        material = None
    if material is not None and not material.is_approved:
        flash(request, "Chỉ soạn câu hỏi từ tài liệu đã duyệt.", "danger")
        return redirect(f"/mon-hoc/{course.id}/cau-hoi")
    topic = next((t for t in course.topics if t.id == (tid or (material.topic_id if material else None))), None)
    if topic is None:
        flash(request, "Hãy chọn chủ đề cho câu hỏi.", "danger")
        return redirect(f"/mon-hoc/{course.id}/cau-hoi")
    if material is not None:
        text = material.content
    else:
        text = "\n\n".join(m.content for m in course.materials if m.is_approved and m.topic_id == topic.id)
    if not text.strip():
        flash(request, "Chủ đề này chưa có tài liệu đã duyệt để AI dựa vào.", "danger")
        return redirect(f"/mon-hoc/{course.id}/cau-hoi")
    request_obj = QuestionGenRequest(
        subject_name=course.name,
        topic_name=topic.name,
        material_text=text,
        count=max(1, min(10, count)),
        difficulty=max(1, min(4, difficulty)),
        kind=kind if kind in ("mcq", "short", "mixed") else "mixed",
    )
    try:
        generated = request.app.state.ai.generate_questions(request_obj)
    except AIError as exc:
        flash(request, f"AI chưa soạn được câu hỏi: {exc}", "danger")
        return redirect(f"/mon-hoc/{course.id}/cau-hoi")
    n = 0
    for g in generated:
        if g.kind == "mcq" and (len(g.options) < 2 or g.correct_option is None or not 0 <= g.correct_option < len(g.options)):
            continue
        db.add(
            Question(
                course_id=course.id,
                topic_id=topic.id,
                kind=g.kind,
                stem=g.stem.strip(),
                options=[o.strip() for o in g.options] if g.kind == "mcq" else [],
                correct_option=g.correct_option if g.kind == "mcq" else None,
                answer=g.answer.strip() if g.kind != "mcq" else "",
                solution="\n".join(s.strip() for s in g.solution_steps if s.strip()),
                difficulty=max(1, min(4, g.difficulty or difficulty)),
                purpose=purpose if purpose in PURPOSES else "practice",
                status="draft",
                source="ai",
            )
        )
        n += 1
    db.commit()
    if n:
        flash(request, f"AI đã soạn {n} câu hỏi nháp. Hãy kiểm tra, sửa nếu cần rồi duyệt.", "info")
    else:
        flash(request, "AI chưa soạn được câu nào phù hợp từ tài liệu này.", "warning")
    return redirect(f"/mon-hoc/{course.id}/cau-hoi?status=draft")
