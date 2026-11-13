"""Xuất dữ liệu thực nghiệm ra CSV (mở bằng Excel, SPSS, R...). Chỉ dùng mã học sinh, không xuất họ tên
trong tệp nhật ký tương tác để thuận tiện ẩn danh hóa khi công bố."""

from __future__ import annotations

import csv
import io

from sqlalchemy.orm import Session

from ..models import MODE_GROUPS, Course
from ..utils.timeutil import fmt_local
from .experiment import course_students, student_rows


def _csv(rows: list[list]) -> str:
    buf = io.StringIO()
    buf.write("﻿")  # BOM để Excel đọc đúng tiếng Việt
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue()


def _num(x, digits: int = 3):
    return "" if x is None else round(x, digits)


def anon_id(student) -> str:
    return f"HS{student.id:04d}"


def students_csv(db: Session, course: Course, include_names: bool = True) -> str:
    header = ["ma_an_danh", "lop", "nhom", "che_do", "diem_dau_vao", "diem_sau_hoc", "diem_ghi_nho", "tien_bo",
              "muc_giam_ghi_nho", "so_cau_luyen", "ti_le_tu_giai", "muc_ho_tro_tb", "so_lan_nho_ai_tb",
              "ti_le_xem_loi_giai", "du_lieu_mau"]
    if include_names:
        header[1:1] = ["ho_ten", "ma_hs"]
    rows = [header]
    for r in student_rows(db, course):
        line = [anon_id(r.student), r.student.classroom.name, MODE_GROUPS.get(r.group, r.group), r.group,
                _num(r.pre, 2), _num(r.post, 2), _num(r.retention, 2), _num(r.gain, 2), _num(r.retention_drop, 2),
                r.sessions, _num(r.independent_rate), _num(r.mean_level), _num(r.mean_requests),
                _num(r.solution_rate), int(r.student.is_demo)]
        if include_names:
            line[1:1] = [r.student.full_name, r.student.student_code]
        rows.append(line)
    return _csv(rows)


def sessions_csv(db: Session, course: Course) -> str:
    rows = [["ma_phien", "ma_an_danh", "nhom", "chu_de", "ma_cau", "do_kho", "loai_cau", "bat_dau", "ket_thuc",
             "thoi_gian_giay", "trang_thai", "dung", "so_lan_tra_loi", "so_lan_sai", "so_lan_nho_ai",
             "muc_ho_tro_cao_nhat", "xem_loi_giai", "tu_giai", "kho_khan_cuoi", "p_truoc", "p_sau"]]
    for st in course_students(db, course):
        for s in st.sessions:
            q = s.question
            rows.append([s.id, anon_id(st), s.mode, q.topic.name if q.topic else "", q.id, q.difficulty, q.kind,
                         fmt_local(s.started_at, "%Y-%m-%d %H:%M:%S"), fmt_local(s.ended_at, "%Y-%m-%d %H:%M:%S"),
                         s.duration_seconds if s.duration_seconds is not None else "", s.status,
                         "" if s.correct is None else int(s.correct), s.attempts, s.wrong_attempts, s.hint_requests,
                         s.max_hint_level, int(s.solution_viewed), int(s.independent), s.last_difficulty or "",
                         _num(s.p_before), _num(s.p_after)])
    return _csv(rows)


def messages_csv(db: Session, course: Course) -> str:
    rows = [["ma_phien", "ma_an_danh", "nhom", "thoi_diem", "vai_tro", "loai", "muc_goi_y", "kho_khan",
             "chan_lo_dap_an", "noi_dung"]]
    for st in course_students(db, course):
        for s in st.sessions:
            for m in s.messages:
                meta = m.meta or {}
                rows.append([s.id, anon_id(st), s.mode, fmt_local(m.created_at, "%Y-%m-%d %H:%M:%S"), m.role, m.kind,
                             m.level or "", meta.get("difficulty", ""), int(bool(meta.get("leak_blocked"))),
                             m.content])
    return _csv(rows)
