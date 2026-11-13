"""Kiểm thử các thành phần lõi: BKT, kiểm tra đáp án, chặn lộ đáp án, kho tri thức, thống kê."""

from __future__ import annotations

import math

import pytest

from app.ai.mock import MockProvider
from app.models import Course, Material, PracticeSession, Question, Topic
from app.services import knowledge, mastery, stats
from app.services.tutor import (
    can_view_solution,
    check_answer,
    hint_ceiling,
    leaks_answer,
    normalize_answer,
    redact,
    start_level,
    to_number,
)

AI = MockProvider()
POLICY = {"require_attempt_first": True, "min_attempts_for_solution": 2, "fading": True, "max_level_mastered": 3}


def q(kind="short", answer="", options=None, correct=None, solution="") -> Question:
    return Question(kind=kind, stem="Đề bài", answer=answer, options=options or [], correct_option=correct, solution=solution)


# --- BKT ---------------------------------------------------------------------


def test_bkt_correct_increases_wrong_decreases():
    p = 0.4
    assert mastery.bkt_update(p, 1.0) > p
    assert mastery.bkt_update(p, 0.0, learn=False) < p
    # tín nhiệm càng cao, mức nắm vững sau cập nhật càng cao
    values = [mastery.bkt_update(p, c) for c in (0.0, 0.35, 0.75, 1.0)]
    assert values == sorted(values)


def test_session_credit_penalises_hints_and_solution():
    s = PracticeSession(correct=True, wrong_attempts=0, max_hint_level=0, solution_viewed=False)
    assert mastery.session_credit(s, "short") == 1.0
    s.max_hint_level = 1
    assert mastery.session_credit(s, "short") == pytest.approx(0.95)
    s.max_hint_level = 3
    assert mastery.session_credit(s, "short") == pytest.approx(0.55)
    s.solution_viewed = True
    assert mastery.session_credit(s, "short") == 0.0
    s2 = PracticeSession(correct=True, wrong_attempts=2, max_hint_level=0, solution_viewed=False)
    assert mastery.session_credit(s2, "mcq") == pytest.approx(0.4)


# --- Kiểm tra đáp án ---------------------------------------------------------


def test_check_answer_short_variants():
    question = q(answer="4.5\n4,5")
    assert check_answer(AI, question, "4.5").correct
    assert check_answer(AI, question, " 4,50 ").correct
    assert not check_answer(AI, question, "4").correct
    code = q(answer="n = int(input())")
    assert check_answer(AI, code, "n=int( input() )").correct
    word = q(answer="Khá")
    assert check_answer(AI, word, "kha").correct
    boolean = q(answer="False")
    assert check_answer(AI, boolean, "false").correct
    assert to_number("x = 5") == 5.0
    assert normalize_answer("  Print( A )  ") == "print(a)"


def test_check_answer_mcq():
    question = q(kind="mcq", options=["a", "b", "c", "d"], correct=2)
    assert check_answer(AI, question, "2").correct
    assert check_answer(AI, question, "C").correct
    assert not check_answer(AI, question, "1").correct


def test_leak_guard():
    numeric = q(answer="14")
    assert leaks_answer("Vậy kết quả là 14 nhé", numeric)
    assert leaks_answer("đáp án: 14", numeric)
    assert not leaks_answer("Em tính lũy thừa 2 ** 2 trước, rồi đến phép nhân.", numeric)
    code = q(answer="n = int(input())")
    assert leaks_answer("Em viết n = int(input()) là xong", code)
    assert not leaks_answer("Hàm int() chuyển xâu sang số nguyên.", code)
    boolean = q(answer="False")
    assert not leaks_answer("Biểu thức logic chỉ nhận một trong hai giá trị True hoặc False.", boolean)
    assert leaks_answer("Vậy biểu thức nhận giá trị False.", boolean)
    assert redact("Phép % lấy phần dư. Vậy kết quả là 14. Em thử lại nhé?", numeric) == "Phép % lấy phần dư. Em thử lại nhé?"
    mcq = q(kind="mcq", options=["x", "y", "z", "t"], correct=1)
    assert leaks_answer("Đáp án đúng là B", mcq)
    assert not leaks_answer("Em xem lại khái niệm vòng lặp.", mcq)


# --- Chính sách gợi ý ----------------------------------------------------------


def test_policy_start_and_ceiling():
    assert start_level(0.2, "thieu_kien_thuc") == 2
    assert start_level(0.6, "thieu_kien_thuc") == 1
    assert start_level(0.2, "sai_sot") == 1
    assert hint_ceiling(POLICY, 0.8, 0) == 3  # đã nắm vững: giảm hỗ trợ
    assert hint_ceiling(POLICY, 0.8, 2) == 4  # đã thử đủ số lần: mở lại
    assert hint_ceiling({**POLICY, "fading": False}, 0.9, 0) == 4
    assert hint_ceiling(POLICY, 0.5, 0) == 4


def test_solution_gate():
    s = PracticeSession(mode="adaptive", wrong_attempts=1, max_hint_level=4, solution_viewed=False)
    ok, msg = can_view_solution(s, POLICY)
    assert not ok and "1 lần" in msg
    s.wrong_attempts = 2
    assert can_view_solution(s, POLICY)[0]
    direct = PracticeSession(mode="direct", wrong_attempts=0, max_hint_level=0, solution_viewed=False)
    assert can_view_solution(direct, POLICY)[0]


# --- Kho tri thức --------------------------------------------------------------


def test_chunk_and_retrieve(db, teacher):
    course = Course(teacher_id=teacher.id, name="Tin", policy={})
    db.add(course)
    db.flush()
    t1 = Topic(course_id=course.id, name="Vòng lặp", position=1, prerequisite_ids=[])
    t2 = Topic(course_id=course.id, name="Danh sách", position=2, prerequisite_ids=[])
    db.add_all([t1, t2])
    db.flush()
    long_text = "\n\n".join(f"Đoạn {i}. Vòng lặp for dùng range để lặp lại khối lệnh nhiều lần." for i in range(30))
    pieces = knowledge.chunk_text(long_text, max_chars=300)
    assert len(pieces) > 3 and all(len(p) <= 300 for p in pieces)
    m1 = Material(course_id=course.id, topic_id=t1.id, title="For", content="Hàm range(a, b) tạo dãy số từ a đến b - 1.")
    m2 = Material(course_id=course.id, topic_id=t2.id, title="List", content="Phương thức append thêm phần tử vào cuối danh sách.")
    db.add_all([m1, m2])
    db.flush()
    assert knowledge.retrieve(db, course.id, "range") == []  # chưa duyệt thì chưa vào kho
    knowledge.approve_material(db, m1)
    knowledge.approve_material(db, m2)
    hits = knowledge.retrieve(db, course.id, "thêm phần tử vào danh sách")
    assert hits and hits[0].chunk.material_id == m2.id
    knowledge.approve_material(db, m2, approved=False)
    assert all(h.chunk.material_id != m2.id for h in knowledge.retrieve(db, course.id, "thêm phần tử vào danh sách"))


# --- Thống kê ------------------------------------------------------------------


def test_welch_t_and_cohen_d():
    c = stats.compare([7, 8, 6, 9, 7], [5, 6, 7, 5, 6])
    assert c.t == pytest.approx(2.5298221, rel=1e-6)
    assert c.df == pytest.approx(7.3394495, rel=1e-6)
    assert c.p == pytest.approx(0.0377597, rel=1e-5)
    assert c.d == pytest.approx(1.6, rel=1e-6)
    assert c.significant and c.effect_label == "lớn"
    assert stats.t_pvalue(2.0, 10) == pytest.approx(0.0733880, rel=1e-5)
    small = stats.compare([5], [4, 6])
    assert small.p is None and small.mean_a == 5
    assert math.isclose(stats.sd([2, 4, 4, 4, 5, 5, 7, 9]), 2.13809, rel_tol=1e-5)
