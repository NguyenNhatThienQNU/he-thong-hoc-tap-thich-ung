"""Tiện ích xử lý chuỗi tiếng Việt, điểm số và mã đăng nhập."""

from __future__ import annotations

import re
import secrets
import unicodedata

LOGIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bỏ 0/O, 1/I để học sinh khỏi nhầm
LOGIN_CODE_LENGTH = 6


def strip_accents(text: str | None) -> str:
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def norm(text: str | None) -> str:
    """Chuẩn hóa để so khớp: bỏ dấu, chữ thường, gộp khoảng trắng."""
    return re.sub(r"\s+", " ", strip_accents(text or "").lower()).strip()


def norm_key(text: str | None) -> str:
    """Chuẩn hóa mạnh (chỉ giữ chữ và số), dùng cho tên cột bảng tính."""
    return re.sub(r"[^a-z0-9]+", "", norm(text))


def new_login_code() -> str:
    return "".join(secrets.choice(LOGIN_ALPHABET) for _ in range(LOGIN_CODE_LENGTH))


def clean_code(text: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "").upper()


def fmt_score(value: float | None, digits: int = 2) -> str:
    """Hiển thị số kiểu Việt Nam: 7.5 -> '7,5'; 8.0 -> '8'."""
    if value is None:
        return "–"
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", ",")


def fmt_pct(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "–"
    return fmt_score(value * 100, digits) + "%"


def truncate(text: str | None, length: int = 80) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def split_lines(text: str | None) -> list[str]:
    """Tách văn bản thành các dòng không rỗng (dùng cho các bước lời giải)."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


OPTION_LETTERS = "ABCDEFGH"


def option_letter(index: int | None) -> str:
    if index is None or index < 0 or index >= len(OPTION_LETTERS):
        return "?"
    return OPTION_LETTERS[index]


def vn_name_key(full_name: str) -> tuple[str, str]:
    """Khóa sắp xếp họ tên kiểu Việt Nam: theo tên (từ cuối) rồi đến họ và tên đệm."""
    parts = norm(full_name).split()
    return (parts[-1] if parts else "", " ".join(parts))
