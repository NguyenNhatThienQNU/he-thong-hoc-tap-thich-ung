"""Cấu hình chung cho kiểm thử: CSDL SQLite tạm, AI chế độ demo."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import SessionLocal
from app.main import create_app
from app.models import Teacher
from app.security import hash_password


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, secret_key="khoa-kiem-thu", ai_provider="mock")


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def db(app):
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def teacher(db) -> Teacher:
    t = Teacher(full_name="Cô Lan", email="lan@truong.vn", password_hash=hash_password("matkhau1"))
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def demo(db, teacher):
    """Môn Tin học 10 mẫu, lớp 12 học sinh có lịch sử luyện tập mô phỏng."""
    from app.seed import seed_demo_data

    course, classroom = seed_demo_data(db, teacher)
    db.commit()
    return course, classroom


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert match, "Không thấy CSRF token trong trang"
    return match.group(1)


def login(client: TestClient, email: str, password: str) -> None:
    token = csrf_of(client.get("/login").text)
    r = client.post("/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303, r.text


@pytest.fixture
def client(app, teacher):
    with TestClient(app) as c:
        login(c, "lan@truong.vn", "matkhau1")
        c.csrf = csrf_of(c.get("/cai-dat").text)
        yield c
