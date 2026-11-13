"""Điểm vào khi chạy trên Vercel (hàm Python serverless).

Vercel tìm biến `app` (ứng dụng ASGI) trong tệp này; vercel.json chuyển mọi đường dẫn về đây.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import create_app  # noqa: E402

app = create_app()
