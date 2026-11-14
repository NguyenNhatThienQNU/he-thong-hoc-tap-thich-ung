"""Cấu hình ứng dụng, đọc từ biến môi trường hoặc tệp .env ở thư mục gốc dự án."""

from __future__ import annotations

import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
# Vercel đặt biến môi trường VERCEL=1; mã nguồn ở đó chỉ đọc, chỉ ghi được vào /tmp
ON_VERCEL = bool(os.environ.get("VERCEL"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Chung ---
    app_name: str = "Trợ lý AI Nâng Tầm Tư Duy Toán – Tin THPT"
    secret_key: str = ""  # để trống: tự sinh và lưu vào data/.secret_key
    data_dir: Path = Path("/tmp/goimo-data") if ON_VERCEL else BASE_DIR / "data"
    database_url: str = ""  # để trống: SQLite tại data/app.db
    postgres_url: str = ""  # tên biến mà Vercel Postgres / Neon tự tạo (POSTGRES_URL)
    timezone: str = "Asia/Ho_Chi_Minh"
    public_base_url: str = "http://localhost:8000"
    allow_registration: bool = True  # Luôn cho phép đăng ký thêm giáo viên

    # --- AI ---
    ai_provider: str = "auto"  # auto | gemini | mock
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    ai_timeout_seconds: int = 120

    # --- Tải tệp ---
    max_upload_mb: int = 4 if ON_VERCEL else 15  # Vercel giới hạn yêu cầu 4,5 MB

    # ------------------------------------------------------------------
    @property
    def resolved_database_url(self) -> str:
        url = (self.database_url or self.postgres_url).strip()
        if url:
            # Neon/Vercel/Render cấp chuỗi postgres:// hoặc postgresql:// – dùng trình điều khiển psycopg 3
            for prefix in ("postgres://", "postgresql://"):
                if url.startswith(prefix):
                    url = "postgresql+psycopg://" + url[len(prefix) :]
            return url
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def uses_ephemeral_db(self) -> bool:
        """Trên Vercel mà chưa nối PostgreSQL: dữ liệu SQLite trong /tmp sẽ mất."""
        return ON_VERCEL and self.resolved_database_url.startswith("sqlite")

    @property
    def effective_ai_provider(self) -> str:
        provider = self.ai_provider.strip().lower()
        if provider == "auto":
            return "gemini" if self.gemini_api_key else "mock"
        return provider

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_secret_key(self) -> str:
        """Khóa ký phiên đăng nhập. Nếu chưa cấu hình thì sinh một lần và lưu lại."""
        if self.secret_key:
            return self.secret_key
        if ON_VERCEL:
            # Nhiều máy chủ chạy song song nên khóa phải cố định: suy ra từ chuỗi kết nối CSDL
            return hashlib.sha256(("goimo:" + self.resolved_database_url).encode()).hexdigest()
        self.ensure_dirs()
        key_file = self.data_dir / ".secret_key"
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
        key = secrets.token_urlsafe(48)
        key_file.write_text(key, encoding="utf-8")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
