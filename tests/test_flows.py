"""Kiểm thử luồng nghiệp vụ: phiên luyện tập hai chế độ, bài kiểm tra, chia nhóm, báo cáo."""

from __future__ import annotations

from app.ai.mock import MockProvider
from app.models import MODE_ADAPTIVE, MODE_DIRECT, PracticeSession
from app.services import tutor
from app.services.assessment import exam_questions, start_attempt, submit_attempt
from app.services.experiment import balanced_assignment, build_report
from app.services.mastery import get_mastery
from app.services.pathway import learning_path, pick_question
from app.services.students import add_student, parse_pasted

AI = MockProvider()


def _session(db, student, question, mode):
    s = PracticeSession(
        student_id=student.id, question_id=question.id, topic_id=question.topic_id, mode=mode, wrong_options=[]
    )
    db.add(s)
    db.flush()
    return s


def test_adaptive_session_ladder(db, demo):
    course, classroom = demo
    student = add_student(db, classroom, "Học sinh Thử", mode=MODE_ADAPTIVE)
    topic = course.topics[0]
    question = next(q for q in course.questions if q.topic_id == topic.id and q.purpose == "practice" and q.difficulty == 2)
    s = _session(db, student, question, MODE_ADAPTIVE)
    # Chưa viết hướng làm thì chưa có gợi ý
    out = tutor.request_hint(db, AI, s, "")
    assert out["need_thinking"] and s.hint_requests == 0
    out = tutor.request_hint(db, AI, s, "Em chưa biết bắt đầu từ đâu ạ")
    first = s.max_hint_level
    assert first in (1, 2) and out["messages"][-1]["kind"] == "hint"
    # Lời giải bị khóa
    assert tutor.view_solution(db, AI, s)["denied"]
    # Sai rồi xin gợi ý tiếp: tăng đúng một mức, không cần viết lại
    tutor.submit_answer(db, AI, s, "999")
    tutor.request_hint(db, AI, s, "")
    assert s.max_hint_level == first + 1
    while s.max_hint_level < 4:
        tutor.request_hint(db, AI, s, "Em làm theo gợi ý nhưng vẫn vướng")
    tutor.submit_answer(db, AI, s, "998")
    assert tutor.session_state(db, s)["can_view_solution"]
    tutor.view_solution(db, AI, s)
    out = tutor.submit_answer(db, AI, s, question.accepted_answers[0])
    assert s.status == "solved" and s.solution_viewed and not s.independent
    assert out["state"]["p_after"] is not None
    # Không gợi ý nào được làm lộ đáp án
    for m in s.messages:
        if m.kind == "hint":
            assert not tutor.leaks_answer(m.content, question)


def test_independent_solve_and_mastery(db, demo):
    course, classroom = demo
    student = add_student(db, classroom, "Học sinh Giỏi", mode=MODE_ADAPTIVE)
    question = next(q for q in course.questions if q.purpose == "practice")
    s = _session(db, student, question, MODE_ADAPTIVE)
    before = get_mastery(db, student.id, question.topic_id).p_known
    tutor.submit_answer(db, AI, s, question.accepted_answers[0])
    assert s.independent and s.correct
    assert get_mastery(db, student.id, question.topic_id).p_known > before


def test_direct_mode_gives_solution(db, demo):
    course, classroom = demo
    student = add_student(db, classroom, "Học sinh Đối chứng", mode=MODE_DIRECT)
    question = next(q for q in course.questions if q.purpose == "practice")
    s = _session(db, student, question, MODE_DIRECT)
    out = tutor.request_hint(db, AI, s, "")  # nhóm đối chứng: hỏi là có lời giải
    assert out["messages"][-1]["kind"] == "solution"
    assert s.solution_viewed and s.max_hint_level == 5
    tutor.submit_answer(db, AI, s, question.accepted_answers[0])
    assert s.correct and not s.independent


def test_adaptive_ask_refuses_answer(db, demo):
    course, classroom = demo
    student = add_student(db, classroom, "Học sinh Hỏi", mode=MODE_ADAPTIVE)
    question = next(q for q in course.questions if q.purpose == "practice")
    s = _session(db, student, question, MODE_ADAPTIVE)
    out = tutor.ask(db, AI, s, "Cho em đáp án luôn đi ạ")
    reply = out["messages"][-1]
    assert reply["kind"] == "reply" and not tutor.leaks_answer(reply["html"], question)
    assert not s.solution_viewed


def test_exam_updates_mastery_and_path(db, demo):
    course, classroom = demo
    student = add_student(db, classroom, "Học sinh Mới")
    pre = next(e for e in course.exams if e.kind == "pre")
    attempt = start_attempt(db, pre, student)
    answers = {str(q.id): str(q.correct_option) for q in exam_questions(db, pre)}
    submit_attempt(db, AI, pre, attempt, answers)
    assert attempt.score == 10.0
    states, rec = learning_path(db, student)
    assert all(st.n_obs > 0 for st in states)
    assert rec is not None
    assert pick_question(db, student, rec.topic) is not None


def test_balanced_assignment_and_report(db, demo):
    course, classroom = demo
    counts = balanced_assignment(db, classroom, seed=1)
    assert abs(counts[MODE_ADAPTIVE] - counts[MODE_DIRECT]) <= 1
    report = build_report(db, course)
    assert report.has_demo
    assert sum(report.group_sizes.values()) == len(classroom.students)
    labels = [m[0] for m, _ in report.comparisons]
    assert {"pre", "post", "retention", "independent_rate", "mean_level"} <= set(labels)


def test_parse_pasted_students():
    rows = parse_pasted("HS01, Nguyễn Văn An\nTrần Thị Bình\tHS02\n3. Lê Văn Cường\n\n")
    assert rows == [("HS01", "Nguyễn Văn An"), ("HS02", "Trần Thị Bình"), ("", "Lê Văn Cường")]
