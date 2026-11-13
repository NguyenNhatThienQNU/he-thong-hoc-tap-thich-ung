"""Lệnh quản trị.

  python -m app.cli create-teacher --name "Nguyễn Văn A" --email a@truong.edu.vn --password matkhau
  python -m app.cli reset-password --email a@truong.edu.vn --password matkhaumoi
  python -m app.cli seed-demo            # tài khoản demo@truonghoc.vn / demo1234 kèm dữ liệu mẫu
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from .config import get_settings
from .db import create_tables, init_engine, session_scope
from .models import Teacher
from .security import hash_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-teacher")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p = sub.add_parser("reset-password")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    sub.add_parser("seed-demo")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.ensure_dirs()
    init_engine(settings.resolved_database_url)
    create_tables()

    with session_scope() as db:
        if args.cmd == "create-teacher":
            email = args.email.strip().lower()
            if db.scalar(select(Teacher).where(func.lower(Teacher.email) == email)):
                print("Email đã tồn tại.")
                return 1
            db.add(Teacher(full_name=args.name, email=email, password_hash=hash_password(args.password)))
            print(f"Đã tạo tài khoản {email}.")
        elif args.cmd == "reset-password":
            teacher = db.scalar(select(Teacher).where(func.lower(Teacher.email) == args.email.strip().lower()))
            if teacher is None:
                print("Không tìm thấy tài khoản.")
                return 1
            teacher.password_hash = hash_password(args.password)
            print("Đã đặt lại mật khẩu.")
        elif args.cmd == "seed-demo":
            from .seed import seed_demo_data

            teacher = db.scalar(select(Teacher).where(Teacher.email == "demo@truonghoc.vn"))
            if teacher is None:
                teacher = Teacher(full_name="Giáo viên Demo", email="demo@truonghoc.vn", password_hash=hash_password("demo1234"))
                db.add(teacher)
                db.flush()
            course, classroom = seed_demo_data(db, teacher)
            print(f"Đã nạp dữ liệu mẫu: {course.name} – lớp {classroom.name}.")
            print("Đăng nhập: demo@truonghoc.vn / demo1234")
    return 0


if __name__ == "__main__":
    sys.exit(main())
