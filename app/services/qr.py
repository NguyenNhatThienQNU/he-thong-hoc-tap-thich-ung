"""Mã QR trên phiếu đăng nhập của học sinh."""

from __future__ import annotations

import segno


def qr_svg(data: str, scale: int = 3) -> str:
    """Trả về chuỗi SVG nhúng thẳng vào HTML."""
    return segno.make(data, error="m").svg_inline(scale=scale, border=2)
