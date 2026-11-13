"""Báo cáo thực nghiệm so sánh hai nhóm và xuất dữ liệu CSV."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..models import MODE_ADAPTIVE, MODE_DIRECT, Teacher
from ..services import exporter
from ..services.experiment import build_report, exam_kind_counts
from .deps import current_teacher, get_db, owned_course, render

router = APIRouter()


@router.get("/mon-hoc/{course_id}/thuc-nghiem")
def report_page(course_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    course = owned_course(db, teacher, course_id)
    report = build_report(db, course)
    chart = {
        "weeks": report.weeks,
        "adaptive_level": [p["mean_level"] for p in report.trend[MODE_ADAPTIVE]],
        "direct_level": [p["mean_level"] for p in report.trend[MODE_DIRECT]],
        "adaptive_indep": [p["independent_rate"] for p in report.trend[MODE_ADAPTIVE]],
        "direct_indep": [p["independent_rate"] for p in report.trend[MODE_DIRECT]],
    }
    return render(
        request,
        "course/experiment.html",
        teacher=teacher,
        active="courses",
        tab="experiment",
        course=course,
        report=report,
        chart=chart,
        exam_counts=exam_kind_counts(course),
    )


def _csv_response(text: str, filename: str) -> Response:
    return Response(
        content=text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/mon-hoc/{course_id}/thuc-nghiem/hoc-sinh.csv")
def export_students(
    course_id: int, an_danh: int = 0, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    course = owned_course(db, teacher, course_id)
    return _csv_response(exporter.students_csv(db, course, include_names=not an_danh), f"hoc-sinh-mon-{course.id}.csv")


@router.get("/mon-hoc/{course_id}/thuc-nghiem/phien.csv")
def export_sessions(course_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    course = owned_course(db, teacher, course_id)
    return _csv_response(exporter.sessions_csv(db, course), f"phien-luyen-tap-mon-{course.id}.csv")


@router.get("/mon-hoc/{course_id}/thuc-nghiem/tuong-tac.csv")
def export_messages(course_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    course = owned_course(db, teacher, course_id)
    return _csv_response(exporter.messages_csv(db, course), f"tuong-tac-ai-mon-{course.id}.csv")
