"""Trang công khai: trang chủ chọn vai trò, giới thiệu đề tài, kiểm tra tình trạng máy chủ."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..models import Teacher
from .deps import get_db, render

router = APIRouter()


@router.get("/")
def home(request: Request):
    return render(request, "public/landing.html")


@router.get("/gioi-thieu")
def about(request: Request, db: Session = Depends(get_db)):
    teacher_id = request.session.get("teacher_id")
    teacher = db.get(Teacher, teacher_id) if teacher_id else None
    return render(request, "public/about.html", teacher=teacher)


@router.get("/healthz")
def healthz():
    return {"ok": True}
