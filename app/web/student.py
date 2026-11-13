"""Giao diện học sinh: đăng nhập bằng mã, lộ trình cá nhân, luyện tập cùng AI, làm bài kiểm tra."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..models import Exam, PracticeSession, Student, Topic
from ..services import tutor
from ..services.assessment import exam_questions, get_attempt, seconds_left, start_attempt, submit_attempt
from ..services.mastery import get_mastery
from ..services.pathway import active_session, learning_path, pick_question, student_stats
from ..utils.text import clean_code
from ..utils.timeutil import utcnow
from .deps import current_student, flash, get_db, not_found, redirect, render, verify_csrf

router = APIRouter(prefix="/hs", dependencies=[Depends(verify_csrf)])


# ---------------------------------------------------------------------------
# Đăng nhập
# ---------------------------------------------------------------------------


def _login(request: Request, student: Student) -> None:
    request.session["student_id"] = student.id


@router.get("/dang-nhap")
def login_page(request: Request, ma: str = ""):
    if request.session.get("student_id"):
        return redirect("/hs")
    return render(request, "student/login.html", code=clean_code(ma))


@router.post("/dang-nhap")
def login(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).where(Student.login_code == clean_code(code)))
    if student is None:
        return render(request, "student/login.html", code=clean_code(code), error="Mã đăng nhập không đúng.", status_code=400)
    _login(request, student)
    return redirect("/hs")


@router.get("/vao/{code}")
def login_by_link(code: str, request: Request, db: Session = Depends(get_db)):
    student = db.scalar(select(Student).where(Student.login_code == clean_code(code)))
    if student is None:
        return redirect(f"/hs/dang-nhap?ma={clean_code(code)}")
    _login(request, student)
    return redirect("/hs")


@router.post("/dang-xuat")
def logout(request: Request):
    request.session.pop("student_id", None)
    return redirect("/hs/dang-nhap")


# ---------------------------------------------------------------------------
# Trang chủ, chủ đề
# ---------------------------------------------------------------------------


def _open_exams(student: Student) -> list[Exam]:
    return [e for e in student.classroom.course.exams if e.is_open]


def _pending_pre_exam(db: Session, student: Student) -> Exam | None:
    for exam in _open_exams(student):
        if exam.kind == "pre":
            att = get_attempt(db, exam, student)
            if att is None or att.submitted_at is None:
                return exam
    return None


@router.get("")
def home(request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)):
    states, rec = learning_path(db, student)
    exams = []
    for exam in _open_exams(student):
        exams.append((exam, get_attempt(db, exam, student)))
    return render(
        request,
        "student/home.html",
        student=student,
        states=states,
        rec=rec,
        exams=exams,
        pending_pre=_pending_pre_exam(db, student),
        stats=student_stats(db, student),
        resume=active_session(db, student),
        recent=sorted(student.sessions, key=lambda s: s.started_at, reverse=True)[:8],
    )


def _own_topic(db: Session, student: Student, topic_id: int) -> Topic:
    topic = db.get(Topic, topic_id)
    if topic is None or topic.course_id != student.classroom.course_id:
        raise not_found()
    return topic


@router.get("/chu-de/{topic_id}")
def topic_page(topic_id: int, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)):
    topic = _own_topic(db, student, topic_id)
    m = get_mastery(db, student.id, topic.id)
    db.commit()
    materials = [mat for mat in topic.materials if mat.is_approved]
    sessions = [s for s in student.sessions if s.topic_id == topic.id]
    sessions.sort(key=lambda s: s.started_at, reverse=True)
    return render(
        request,
        "student/topic.html",
        student=student,
        topic=topic,
        mastery=m,
        materials=materials,
        sessions=sessions[:10],
        pending_pre=_pending_pre_exam(db, student),
    )


# ---------------------------------------------------------------------------
# Luyện tập
# ---------------------------------------------------------------------------


@router.post("/luyen-tap")
def start_practice(
    request: Request,
    topic_id: int = Form(...),
    new: str = Form(""),
    db: Session = Depends(get_db),
    student: Student = Depends(current_student),
):
    topic = _own_topic(db, student, topic_id)
    pre = _pending_pre_exam(db, student)
    if pre is not None:
        flash(request, "Em hãy làm bài kiểm tra đầu vào trước để hệ thống xây dựng lộ trình phù hợp.", "warning")
        return redirect(f"/hs/kiem-tra/{pre.id}")
    current = active_session(db, student, topic.id)
    if current is not None and not new:
        return redirect(f"/hs/luyen-tap/{current.id}")
    if current is not None:  # học sinh chủ động chuyển câu khác: phiên cũ tính là bỏ qua
        tutor.give_up(db, current)
    question = pick_question(db, student, topic)
    if question is None:
        db.commit()
        flash(request, "Chủ đề này chưa có câu luyện tập. Em chọn chủ đề khác nhé.", "warning")
        return redirect(f"/hs/chu-de/{topic.id}")
    m = get_mastery(db, student.id, topic.id)
    session = PracticeSession(
        student_id=student.id,
        question_id=question.id,
        topic_id=topic.id,
        mode=student.effective_mode,
        status="active",
        started_at=utcnow(),
        p_before=m.p_known,
        wrong_options=[],
    )
    db.add(session)
    db.commit()
    return redirect(f"/hs/luyen-tap/{session.id}")


def _own_session(db: Session, student: Student, session_id: int) -> PracticeSession:
    session = db.get(PracticeSession, session_id)
    if session is None or session.student_id != student.id:
        raise not_found()
    return session


@router.get("/luyen-tap/{session_id}")
def practice_page(
    session_id: int, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)
):
    session = _own_session(db, student, session_id)
    state = tutor.session_state(db, session)
    db.commit()
    return render(
        request,
        "student/practice.html",
        student=student,
        s=session,
        q=session.question,
        topic=session.question.topic,
        state=state,
        messages=[tutor.message_dict(m) for m in session.messages],
        policy=session.question.course.full_policy,
    )


class AnswerIn(BaseModel):
    answer: str = ""


class ThinkingIn(BaseModel):
    thinking: str = ""


class AskIn(BaseModel):
    text: str = ""


def _api(db: Session, fn, *args) -> JSONResponse:
    try:
        result = fn(*args)
    except tutor.TutorError as exc:
        db.rollback()
        return JSONResponse({"detail": str(exc)}, status_code=400)
    db.commit()
    return JSONResponse(result)


@router.post("/api/phien/{session_id}/tra-loi")
def api_answer(
    session_id: int, body: AnswerIn, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)
):
    session = _own_session(db, student, session_id)
    return _api(db, tutor.submit_answer, db, request.app.state.ai, session, body.answer)


@router.post("/api/phien/{session_id}/goi-y")
def api_hint(
    session_id: int, body: ThinkingIn, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)
):
    session = _own_session(db, student, session_id)
    return _api(db, tutor.request_hint, db, request.app.state.ai, session, body.thinking)


@router.post("/api/phien/{session_id}/hoi")
def api_ask(
    session_id: int, body: AskIn, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)
):
    session = _own_session(db, student, session_id)
    return _api(db, tutor.ask, db, request.app.state.ai, session, body.text)


@router.post("/api/phien/{session_id}/loi-giai")
def api_solution(
    session_id: int, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)
):
    session = _own_session(db, student, session_id)
    return _api(db, tutor.view_solution, db, request.app.state.ai, session)


@router.post("/api/phien/{session_id}/bo-qua")
def api_give_up(session_id: int, db: Session = Depends(get_db), student: Student = Depends(current_student)):
    session = _own_session(db, student, session_id)
    return _api(db, tutor.give_up, db, session)


# ---------------------------------------------------------------------------
# Bài kiểm tra (không có AI)
# ---------------------------------------------------------------------------


def _own_exam(db: Session, student: Student, exam_id: int) -> Exam:
    exam = db.get(Exam, exam_id)
    if exam is None or exam.course_id != student.classroom.course_id:
        raise not_found()
    return exam


@router.get("/kiem-tra/{exam_id}")
def exam_page(exam_id: int, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)):
    exam = _own_exam(db, student, exam_id)
    attempt = get_attempt(db, exam, student)
    if attempt is not None and attempt.submitted_at is not None:
        return redirect(f"/hs/kiem-tra/{exam.id}/ket-qua")
    if not exam.is_open:
        raise HTTPException(status_code=403, detail="Bài kiểm tra này chưa mở hoặc đã đóng.")
    attempt = start_attempt(db, exam, student)
    db.commit()
    return render(
        request,
        "student/exam.html",
        student=student,
        exam=exam,
        attempt=attempt,
        questions=exam_questions(db, exam),
        seconds_left=seconds_left(exam, attempt),
    )


@router.post("/kiem-tra/{exam_id}")
async def exam_submit(exam_id: int, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)):
    exam = _own_exam(db, student, exam_id)
    attempt = get_attempt(db, exam, student)
    if attempt is None:
        return redirect(f"/hs/kiem-tra/{exam.id}")
    form = await request.form()
    answers = {k[2:]: str(v) for k, v in form.items() if k.startswith("q_")}
    await run_in_threadpool(submit_attempt, db, request.app.state.ai, exam, attempt, answers)
    db.commit()
    return redirect(f"/hs/kiem-tra/{exam.id}/ket-qua")


@router.get("/kiem-tra/{exam_id}/ket-qua")
def exam_result(exam_id: int, request: Request, db: Session = Depends(get_db), student: Student = Depends(current_student)):
    exam = _own_exam(db, student, exam_id)
    attempt = get_attempt(db, exam, student)
    if attempt is None or attempt.submitted_at is None:
        return redirect(f"/hs/kiem-tra/{exam.id}")
    return render(
        request,
        "student/exam_result.html",
        student=student,
        exam=exam,
        attempt=attempt,
        questions=exam_questions(db, exam),
    )
