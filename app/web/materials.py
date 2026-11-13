"""Kho tri thức: giáo viên tải tài liệu, kiểm duyệt, thử tra cứu."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from ..models import Material, Teacher
from ..services.knowledge import ExtractError, approve_material, clean_text, extract_text, reindex_material, retrieve
from .deps import (
    current_teacher,
    flash,
    form_int,
    get_db,
    owned_course,
    owned_material,
    redirect,
    render,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


@router.get("/mon-hoc/{course_id}/tai-lieu")
def material_list(
    course_id: int,
    request: Request,
    q: str = "",
    topic: int | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    hits = retrieve(db, course.id, q, topic_id=topic, k=5) if q.strip() else []
    return render(
        request,
        "course/materials.html",
        teacher=teacher,
        active="courses",
        tab="materials",
        course=course,
        query=q,
        query_topic=topic,
        hits=hits,
    )


@router.post("/mon-hoc/{course_id}/tai-lieu")
async def material_create(
    course_id: int,
    request: Request,
    title: str = Form(""),
    topic_id: str = Form(""),
    content: str = Form(""),
    approve_now: str = Form(""),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    filename = ""
    text = content
    if file is not None and file.filename:
        data = await file.read()
        limit = request.app.state.settings.max_upload_mb * 1024 * 1024
        if len(data) > limit:
            flash(request, f"Tệp quá lớn (tối đa {request.app.state.settings.max_upload_mb} MB).", "danger")
            return redirect(f"/mon-hoc/{course.id}/tai-lieu")
        try:
            text = extract_text(file.filename, data)
        except ExtractError as exc:
            flash(request, str(exc), "danger")
            return redirect(f"/mon-hoc/{course.id}/tai-lieu")
        filename = file.filename
    text = clean_text(text)
    if not text:
        flash(request, "Tài liệu chưa có nội dung. Hãy chọn tệp hoặc dán văn bản.", "danger")
        return redirect(f"/mon-hoc/{course.id}/tai-lieu")
    tid = form_int(topic_id)
    if tid is not None and tid not in {t.id for t in course.topics}:
        tid = None
    material = Material(
        course_id=course.id,
        topic_id=tid,
        title=(" ".join(title.split()) or (filename.rsplit(".", 1)[0] if filename else "Tài liệu không tên"))[:250],
        content=text,
        filename=filename[:250],
        status="pending",
    )
    db.add(material)
    db.flush()
    if approve_now == "on":
        n = approve_material(db, material, True)
        flash(request, f"Đã thêm và duyệt tài liệu ({n} đoạn tri thức được đưa vào kho).")
    else:
        flash(request, "Đã thêm tài liệu. Hãy đọc lại, chỉnh sửa nếu cần rồi bấm “Duyệt”.", "info")
    db.commit()
    return redirect(f"/tai-lieu/{material.id}")


@router.get("/tai-lieu/{material_id}")
def material_detail(
    material_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    material = owned_material(db, teacher, material_id)
    return render(
        request,
        "course/material.html",
        teacher=teacher,
        active="courses",
        tab="materials",
        course=material.course,
        material=material,
    )


@router.post("/tai-lieu/{material_id}/sua")
def material_update(
    material_id: int,
    request: Request,
    title: str = Form(""),
    topic_id: str = Form(""),
    content: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    material = owned_material(db, teacher, material_id)
    if " ".join(title.split()):
        material.title = " ".join(title.split())
    tid = form_int(topic_id)
    material.topic_id = tid if tid in {t.id for t in material.course.topics} else None
    text = clean_text(content)
    if text:
        material.content = text
    db.flush()
    n = reindex_material(db, material)
    db.commit()
    flash(request, "Đã lưu tài liệu." + (f" Kho tri thức được cập nhật ({n} đoạn)." if material.is_approved else ""))
    return redirect(f"/tai-lieu/{material.id}")


@router.post("/tai-lieu/{material_id}/duyet")
def material_approve(
    material_id: int,
    request: Request,
    action: str = Form("approve"),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    material = owned_material(db, teacher, material_id)
    if action == "unapprove":
        approve_material(db, material, False)
        flash(request, "Đã gỡ duyệt. AI sẽ không dùng tài liệu này nữa.", "warning")
    else:
        n = approve_material(db, material, True)
        flash(request, f"Đã duyệt. {n} đoạn tri thức được đưa vào kho để AI tra cứu khi gợi ý.")
    db.commit()
    return redirect(f"/tai-lieu/{material.id}")


@router.post("/tai-lieu/{material_id}/xoa")
def material_delete(
    material_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    material = owned_material(db, teacher, material_id)
    course_id = material.course_id
    db.delete(material)
    db.commit()
    flash(request, "Đã xóa tài liệu.")
    return redirect(f"/mon-hoc/{course_id}/tai-lieu")
