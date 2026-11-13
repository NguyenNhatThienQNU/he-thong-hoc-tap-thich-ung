"""Lớp học, học sinh, chia nhóm thực nghiệm, phiếu đăng nhập, hồ sơ học sinh và nhật ký phiên."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MODE_ADAPTIVE, MODE_DIRECT, MODE_LABELS, Classroom, ExamAttempt, Teacher
from ..services.experiment import balanced_assignment, student_rows
from ..services.mastery import topic_states
from ..services.pathway import student_stats
from ..services.qr import qr_svg
from ..services.students import ImportFormatError, import_students, parse_file, parse_pasted, unique_login_code
from ..utils.text import vn_name_key
from .deps import (
    current_teacher,
    flash,
    get_db,
    owned_classroom,
    owned_course,
    owned_session,
    owned_student,
    public_url,
    redirect,
    render,
    teacher_classes,
    teacher_courses,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


@router.get("/lop")
def class_list(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    return render(
        request,
        "classes/list.html",
        teacher=teacher,
        active="classes",
        classes=teacher_classes(db, teacher),
        courses=teacher_courses(db, teacher),
    )


@router.post("/lop")
def class_create(
    request: Request,
    name: str = Form(...),
    course_id: int = Form(...),
    default_mode: str = Form(MODE_ADAPTIVE),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    course = owned_course(db, teacher, course_id)
    classroom = Classroom(
        teacher_id=teacher.id,
        course_id=course.id,
        name=" ".join(name.split()) or "Lớp mới",
        default_mode=default_mode if default_mode in MODE_LABELS else MODE_ADAPTIVE,
    )
    db.add(classroom)
    db.commit()
    flash(request, f"Đã tạo lớp {classroom.name}. Hãy thêm danh sách học sinh.")
    return redirect(f"/lop/{classroom.id}")


@router.get("/lop/{class_id}")
def class_detail(class_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    classroom = owned_classroom(db, teacher, class_id)
    rows = student_rows(db, classroom.course, students=list(classroom.students))
    topics = classroom.course.topics
    avg_mastery = {}
    for st in classroom.students:
        states = topic_states(db, st, topics)
        seen = [s.p for s in states if s.n_obs > 0]
        avg_mastery[st.id] = sum(seen) / len(seen) if seen else None
    return render(
        request,
        "classes/detail.html",
        teacher=teacher,
        active="classes",
        classroom=classroom,
        rows=rows,
        avg_mastery=avg_mastery,
        counts={m: sum(1 for st in classroom.students if st.effective_mode == m) for m in MODE_LABELS},
    )


@router.post("/lop/{class_id}/sua")
def class_update(
    class_id: int,
    request: Request,
    name: str = Form(...),
    default_mode: str = Form(MODE_ADAPTIVE),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    if " ".join(name.split()):
        classroom.name = " ".join(name.split())
    if default_mode in MODE_LABELS:
        classroom.default_mode = default_mode
    db.commit()
    flash(request, "Đã lưu thông tin lớp.")
    return redirect(f"/lop/{classroom.id}")


@router.post("/lop/{class_id}/xoa")
def class_delete(class_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    classroom = owned_classroom(db, teacher, class_id)
    db.delete(classroom)
    db.commit()
    flash(request, "Đã xóa lớp cùng toàn bộ dữ liệu học sinh của lớp.")
    return redirect("/lop")


@router.post("/lop/{class_id}/hoc-sinh")
async def class_add_students(
    class_id: int,
    request: Request,
    pasted: str = Form(""),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    try:
        if file is not None and file.filename:
            entries = parse_file(await file.read(), file.filename)
        else:
            entries = parse_pasted(pasted)
    except ImportFormatError as exc:
        flash(request, str(exc), "danger")
        return redirect(f"/lop/{classroom.id}")
    if not entries:
        flash(request, "Chưa có học sinh nào để thêm.", "warning")
        return redirect(f"/lop/{classroom.id}")
    created, skipped = import_students(db, classroom, entries)
    db.commit()
    msg = f"Đã thêm {created} học sinh."
    if skipped:
        msg += f" Bỏ qua {skipped} em đã có trong lớp."
    flash(request, msg)
    return redirect(f"/lop/{classroom.id}")


@router.post("/lop/{class_id}/chia-nhom")
def class_assign(
    class_id: int,
    request: Request,
    method: str = Form("balanced"),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    if method == "class":
        for st in classroom.students:
            st.mode = None
        db.commit()
        flash(request, f"Cả lớp dùng chế độ mặc định: {MODE_LABELS[classroom.default_mode]}.")
    else:
        counts = balanced_assignment(db, classroom)
        db.commit()
        flash(
            request,
            f"Đã chia ngẫu nhiên cân bằng theo điểm đầu vào: {counts[MODE_ADAPTIVE]} em nhóm thực nghiệm, "
            f"{counts[MODE_DIRECT]} em nhóm đối chứng.",
        )
    return redirect(f"/lop/{classroom.id}")


@router.post("/hoc-sinh/{student_id}/nhom")
def student_group(
    student_id: int,
    request: Request,
    mode: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    student = owned_student(db, teacher, student_id)
    student.mode = mode if mode in (MODE_ADAPTIVE, MODE_DIRECT) else None
    db.commit()
    return redirect(request.headers.get("referer") or f"/lop/{student.classroom_id}")


@router.post("/hoc-sinh/{student_id}/ma-moi")
def student_new_code(
    student_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    student = owned_student(db, teacher, student_id)
    student.login_code = unique_login_code(db)
    db.commit()
    flash(request, f"Mã đăng nhập mới của {student.full_name}: {student.login_code}")
    return redirect(request.headers.get("referer") or f"/lop/{student.classroom_id}")


@router.post("/hoc-sinh/{student_id}/xem-thu")
def student_impersonate(
    student_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    """Giáo viên mở giao diện học sinh để kiểm tra (mọi thao tác được ghi như học sinh đó làm)."""
    student = owned_student(db, teacher, student_id)
    request.session["student_id"] = student.id
    flash(request, f"Đang xem giao diện của {student.full_name}. Thao tác ở đây được ghi vào dữ liệu của em.", "info")
    return redirect("/hs")


@router.post("/hoc-sinh/{student_id}/xoa")
def student_delete(student_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    student = owned_student(db, teacher, student_id)
    class_id = student.classroom_id
    db.delete(student)
    db.commit()
    flash(request, "Đã xóa học sinh và dữ liệu học tập của em.")
    return redirect(f"/lop/{class_id}")


@router.get("/lop/{class_id}/phieu")
def class_slips(class_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    classroom = owned_classroom(db, teacher, class_id)
    base = public_url(request)
    students = sorted(classroom.students, key=lambda st: vn_name_key(st.full_name))
    slips = [(st, qr_svg(f"{base}/hs/vao/{st.login_code}")) for st in students]
    return render(request, "classes/slips.html", teacher=teacher, active="classes", classroom=classroom, slips=slips, base=base)


@router.get("/hoc-sinh/{student_id}")
def student_profile(student_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    student = owned_student(db, teacher, student_id)
    states = topic_states(db, student, student.classroom.course.topics)
    attempts = list(db.scalars(select(ExamAttempt).where(ExamAttempt.student_id == student.id)).all())
    sessions = sorted(student.sessions, key=lambda s: s.started_at, reverse=True)
    return render(
        request,
        "classes/student.html",
        teacher=teacher,
        active="classes",
        pupil=student,
        states=states,
        stats=student_stats(db, student),
        sessions=sessions,
        attempts=attempts,
    )


@router.get("/phien/{session_id}")
def session_view(session_id: int, request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    session = owned_session(db, teacher, session_id)
    return render(request, "classes/session.html", teacher=teacher, active="classes", s=session, q=session.question)
