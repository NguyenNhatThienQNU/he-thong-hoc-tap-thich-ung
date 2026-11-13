"""Kiểm thử giao diện web: đăng nhập, quyền truy cập, các trang chính, API luyện tập, bài kiểm tra."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.models import Student
from tests.conftest import csrf_of, login


def test_first_teacher_registers(app):
    with TestClient(app) as c:
        assert c.get("/login", follow_redirects=False).headers["location"] == "/register"
        token = csrf_of(c.get("/register").text)
        r = c.post(
            "/register",
            data={"full_name": "Thầy Minh", "email": "minh@x.vn", "password": "123456", "password2": "123456", "csrf_token": token},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert c.get("/dashboard").status_code == 200


def test_csrf_required(client):
    r = client.post("/mon-hoc", data={"name": "Không token"})
    assert r.status_code == 403


def test_login_required(app):
    with TestClient(app) as c:
        r = c.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
        assert c.get("/hs", follow_redirects=False).headers["location"] == "/hs/dang-nhap"


def test_all_teacher_pages_render(client, demo, db):
    course, classroom = demo
    session_id = classroom.students[0].sessions[0].id
    pages = [
        "/dashboard", "/cai-dat", "/gioi-thieu", "/mon-hoc", f"/mon-hoc/{course.id}",
        f"/mon-hoc/{course.id}/tai-lieu", f"/mon-hoc/{course.id}/tai-lieu?q=range",
        f"/tai-lieu/{course.materials[0].id}", f"/mon-hoc/{course.id}/cau-hoi", f"/mon-hoc/{course.id}/cau-hoi/moi",
        f"/cau-hoi/{course.questions[0].id}", f"/mon-hoc/{course.id}/kiem-tra", f"/kiem-tra/{course.exams[0].id}",
        f"/mon-hoc/{course.id}/thuc-nghiem", "/lop", f"/lop/{classroom.id}", f"/lop/{classroom.id}/phieu",
        f"/hoc-sinh/{classroom.students[0].id}", f"/phien/{session_id}",
    ]
    for page in pages:
        r = client.get(page)
        assert r.status_code == 200, page
    assert "số liệu mô phỏng" in client.get(f"/mon-hoc/{course.id}/thuc-nghiem").text
    csv = client.get(f"/mon-hoc/{course.id}/thuc-nghiem/hoc-sinh.csv?an_danh=1")
    assert csv.status_code == 200 and "ma_an_danh" in csv.text and "Nguyễn Minh Anh" not in csv.text
    assert "muc_ho_tro_cao_nhat" in client.get(f"/mon-hoc/{course.id}/thuc-nghiem/phien.csv").text
    assert "noi_dung" in client.get(f"/mon-hoc/{course.id}/thuc-nghiem/tuong-tac.csv").text


def test_other_teacher_cannot_see_data(app, demo, db):
    from app.models import Teacher
    from app.security import hash_password

    course, classroom = demo
    db.add(Teacher(full_name="Người khác", email="khac@x.vn", password_hash=hash_password("123456")))
    db.commit()
    with TestClient(app) as c:
        login(c, "khac@x.vn", "123456")
        assert c.get(f"/mon-hoc/{course.id}").status_code == 404
        assert c.get(f"/lop/{classroom.id}").status_code == 404
        assert c.get(f"/hoc-sinh/{classroom.students[0].id}").status_code == 404


def test_build_course_from_forms(client, db):
    t = client.csrf
    r = client.post("/mon-hoc", data={"name": "Toán 10", "grade": "10", "csrf_token": t}, follow_redirects=False)
    course_url = r.headers["location"]
    cid = int(course_url.rsplit("/", 1)[1])
    client.post(f"/mon-hoc/{cid}/chu-de", data={"name": "Mệnh đề", "csrf_token": t})
    page = client.get(course_url).text
    assert "Mệnh đề" in page
    topic_id = int(re.search(r'/chu-de/(\d+)/sua', page).group(1))
    r = client.post(
        f"/mon-hoc/{cid}/tai-lieu",
        data={"title": "Bài 1", "topic_id": str(topic_id), "content": "Mệnh đề là một câu khẳng định đúng hoặc sai.", "approve_now": "on", "csrf_token": t},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.post(
        f"/mon-hoc/{cid}/cau-hoi",
        data={"topic_id": str(topic_id), "kind": "short", "stem": "2 + 2 = ?", "answer": "4", "solution": "Cộng.\nĐáp án: 4",
              "difficulty": "1", "purpose": "practice", "status": "approved", "csrf_token": t},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.post(f"/mon-hoc/{cid}/cau-hoi/ai", data={"topic_id": str(topic_id), "count": "2", "csrf_token": t}, follow_redirects=False)
    assert r.status_code == 303
    assert client.post(f"/mon-hoc/{cid}/cau-hoi", data={"topic_id": str(topic_id), "kind": "mcq", "stem": "x", "csrf_token": t}).status_code == 400
    r = client.post("/lop", data={"name": "10A9", "course_id": str(cid), "default_mode": "adaptive", "csrf_token": t}, follow_redirects=False)
    class_url = r.headers["location"]
    client.post(f"{class_url}/hoc-sinh", data={"pasted": "HS01, Nguyễn An\nHS02, Trần Bình", "csrf_token": t})
    assert client.get(class_url).text.count('class="login-code"') == 2
    r = client.post(f"/mon-hoc/{cid}/kiem-tra", data={"title": "Đầu vào", "kind": "pre", "duration_min": "10", "per_topic": "1", "csrf_token": t}, follow_redirects=False)
    assert r.status_code == 303


def test_student_practice_via_api(app, client, demo, db):
    course, classroom = demo
    student = db.query(Student).filter(Student.classroom_id == classroom.id).first()
    with TestClient(app) as s:
        r = s.get(f"/hs/vao/{student.login_code}")
        assert r.status_code == 200 and student.first_name in r.text
        token = csrf_of(r.text)
        topic = course.topics[0]
        r = s.post("/hs/luyen-tap", data={"topic_id": str(topic.id), "csrf_token": token}, follow_redirects=False)
        url = r.headers["location"]
        assert url.startswith("/hs/luyen-tap/")
        assert s.get(url).status_code == 200
        sid = url.rsplit("/", 1)[1]
        headers = {"X-CSRF-Token": token}
        assert s.post(f"/hs/api/phien/{sid}/tra-loi", json={"answer": "abc"}).status_code == 403  # thiếu CSRF
        r = s.post(f"/hs/api/phien/{sid}/tra-loi", json={"answer": ""}, headers=headers)
        assert r.status_code == 400
        r = s.post(f"/hs/api/phien/{sid}/hoi", json={"text": "Em chưa hiểu đề bài"}, headers=headers)
        assert r.status_code == 200 and r.json()["messages"]
        r = s.post(f"/hs/api/phien/{sid}/bo-qua", json={}, headers=headers)
        assert r.json()["state"]["status"] in ("given_up",)
        # phiên đã kết thúc thì không thao tác tiếp được
        assert s.post(f"/hs/api/phien/{sid}/goi-y", json={"thinking": "abc"}, headers=headers).status_code == 400
        # học sinh không xem được phiên của bạn khác
        other = classroom.students[-1].sessions[0].id
        assert s.get(f"/hs/luyen-tap/{other}").status_code == 404


def test_pre_exam_gates_practice(app, client, demo, db):
    course, classroom = demo
    pre = next(e for e in course.exams if e.kind == "pre")
    client.post(f"/kiem-tra/{pre.id}/mo", data={"csrf_token": client.csrf})
    token = client.csrf
    client.post(f"/lop/{classroom.id}/hoc-sinh", data={"pasted": "HS50, Học Sinh Mới", "csrf_token": token})
    db.expire_all()
    student = db.query(Student).filter(Student.full_name == "Học Sinh Mới").one()
    with TestClient(app) as s:
        r = s.get(f"/hs/vao/{student.login_code}")
        token = csrf_of(r.text)
        r = s.post("/hs/luyen-tap", data={"topic_id": str(course.topics[0].id), "csrf_token": token}, follow_redirects=False)
        assert r.headers["location"] == f"/hs/kiem-tra/{pre.id}"
        page = s.get(f"/hs/kiem-tra/{pre.id}").text
        qids = set(re.findall(r'name="q_(\d+)"', page))
        r = s.post(f"/hs/kiem-tra/{pre.id}", data={**{f"q_{i}": "0" for i in qids}, "csrf_token": token}, follow_redirects=False)
        assert r.headers["location"].endswith("/ket-qua")
        assert s.get(r.headers["location"]).status_code == 200
        r = s.post("/hs/luyen-tap", data={"topic_id": str(course.topics[0].id), "csrf_token": token}, follow_redirects=False)
        assert r.headers["location"].startswith("/hs/luyen-tap/")
