"""Tiện ích thời gian.

Quy ước: CSDL lưu thời gian UTC dạng "naive" (không kèm múi giờ);
giao diện hiển thị theo giờ Việt Nam (cấu hình được).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

_TZ_NAME = "Asia/Ho_Chi_Minh"


def set_default_timezone(name: str) -> None:
    global _TZ_NAME
    get_tz(name)  # kiểm tra tên múi giờ hợp lệ
    _TZ_NAME = name


@lru_cache(maxsize=8)
def get_tz(name: str | None = None) -> ZoneInfo:
    return ZoneInfo(name or _TZ_NAME)


def utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC (naive) để lưu CSDL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_tz(_TZ_NAME))


def fmt_local(dt: datetime | None, fmt: str = "%H:%M %d/%m/%Y") -> str:
    local = to_local(dt)
    return local.strftime(fmt) if local else ""


def week_start_local(dt: datetime) -> str:
    """Ngày thứ Hai của tuần chứa dt (giờ địa phương), dạng dd/mm – dùng để gom nhóm theo tuần."""
    local = to_local(dt)
    monday = (local - timedelta(days=local.weekday())).date()
    return monday.isoformat()


def humanize_ago(dt: datetime | None, now: datetime | None = None) -> str:
    if dt is None:
        return ""
    now = now or utcnow()
    seconds = max(0, (now - dt).total_seconds())
    if seconds < 60:
        return "vừa xong"
    if seconds < 3600:
        return f"{int(seconds // 60)} phút trước"
    if seconds < 86400:
        return f"{int(seconds // 3600)} giờ trước"
    return f"{int(seconds // 86400)} ngày trước"
