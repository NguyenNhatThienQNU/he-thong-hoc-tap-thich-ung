"""Nhập danh sách học sinh (dán văn bản, tệp Excel/CSV) và cấp mã đăng nhập."""

from __future__ import annotations

import csv
import io
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Classroom, Student
from ..utils.text import new_login_code, norm_key

NAME_KEYS = {"hoten", "hovaten", "ten", "hotenhocsinh", "hovatenhocsinh", "hocsinh", "name", "fullname"}
CODE_KEYS = {"mahs", "mahocsinh", "ma", "mshs", "maso", "code", "studentcode", "stt"}


class ImportFormatError(ValueError):
    pass


def unique_login_code(db: Session) -> str:
    for _ in range(50):
        code = new_login_code()
        if not db.scalar(select(Student.id).where(Student.login_code == code)):
            return code
    raise RuntimeError("Không sinh được mã đăng nhập duy nhất.")


def add_student(db: Session, classroom: Classroom, full_name: str, student_code: str = "", **kwargs) -> Student:
    student = Student(
        classroom_id=classroom.id,
        full_name=" ".join(full_name.split()),
        student_code=student_code.strip(),
        login_code=unique_login_code(db),
        **kwargs,
    )
    db.add(student)
    db.flush()
    return student


def parse_pasted(text: str) -> list[tuple[str, str]]:
    """Mỗi dòng: 'Họ tên' hoặc 'Mã HS, Họ tên' hoặc 'Mã HS<Tab>Họ tên'."""
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[\t,;]", line) if p.strip()]
        if len(parts) >= 2:
            a, b = parts[0], parts[1]
            # mã học sinh không có khoảng trắng, họ tên thì có
            code, name = (b, a) if (" " in a and " " not in b) else (a, b)
        else:
            code, name = "", parts[0]
        name = re.sub(r"^\d+[.)]\s*", "", name)  # bỏ số thứ tự "1. "
        if name:
            out.append((code, name))
    return out


def _rows_from_file(data: bytes, filename: str) -> list[list[str]]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ImportFormatError("Không mở được tệp Excel.") from exc
        rows = [["" if v is None else str(v).strip() for v in row] for row in wb.active.iter_rows(values_only=True)]
        wb.close()
        return rows
    if name.endswith((".csv", ".txt")):
        for enc in ("utf-8-sig", "cp1258", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ImportFormatError("Không đọc được bảng mã của tệp CSV. Hãy lưu dạng 'CSV UTF-8'.")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), dialect)]
    raise ImportFormatError("Chỉ hỗ trợ tệp .xlsx hoặc .csv.")


def parse_file(data: bytes, filename: str) -> list[tuple[str, str]]:
    rows = [r for r in _rows_from_file(data, filename) if any(c.strip() for c in r)]
    if not rows:
        raise ImportFormatError("Tệp không có dữ liệu.")
    for h, header in enumerate(rows[:10]):
        keys = [norm_key(c) for c in header]
        name_col = next((i for i, k in enumerate(keys) if k in NAME_KEYS), None)
        if name_col is None:
            continue
        code_col = next((i for i, k in enumerate(keys) if k in CODE_KEYS and k != "stt"), None)
        out = []
        for row in rows[h + 1 :]:
            name = row[name_col].strip() if name_col < len(row) else ""
            code = row[code_col].strip() if code_col is not None and code_col < len(row) else ""
            if name:
                out.append((code, name))
        return out
    raise ImportFormatError("Không tìm thấy cột 'Họ và tên' trong tệp.")


def import_students(db: Session, classroom: Classroom, entries: list[tuple[str, str]]) -> tuple[int, int]:
    existing = {(norm_key(s.full_name), s.student_code) for s in classroom.students}
    created = skipped = 0
    for code, name in entries:
        key = (norm_key(name), code.strip())
        if key in existing:
            skipped += 1
            continue
        add_student(db, classroom, name, code)
        existing.add(key)
        created += 1
    return created, skipped
