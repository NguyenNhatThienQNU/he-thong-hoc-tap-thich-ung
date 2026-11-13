"""Kho tri thức: đọc tài liệu, cắt đoạn và tra cứu (BM25) để AI gợi ý bám sát tài liệu đã duyệt.

Chỉ tài liệu giáo viên đã duyệt mới được cắt đoạn và đưa vào chỉ mục.
Tra cứu dùng BM25 trên âm tiết tiếng Việt (bỏ dấu) và cặp âm tiết liền nhau,
không cần dịch vụ ngoài nên chạy được cả khi không có mạng.
"""

from __future__ import annotations

import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Material
from ..utils.text import norm
from ..utils.timeutil import utcnow

CHUNK_CHARS = 700
SUPPORTED_EXT = (".txt", ".md", ".docx", ".pdf")

STOPWORDS = set(
    ["la", "va", "cua", "cac", "co", "duoc", "cho", "trong", "mot", "nhung", "voi", "nay", "de", "khi", "thi", "khong", "da", "se", "tu", "ra", "vao", "len", "nhu", "theo", "ve", "tai", "hay", "hoac", "neu", "thi", "ma", "nen", "boi", "vi", "cung", "con", "rat", "nhieu", "it", "hon", "nhat", "cai", "chiec", "em", "ban", "toi", "chung", "ta", "minh", "ai", "gi", "nao", "dau", "sao", "the", "bao", "nhieu"]
)


class ExtractError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Đọc nội dung tệp
# ---------------------------------------------------------------------------


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith((".txt", ".md")):
        for enc in ("utf-8-sig", "cp1258", "cp1252"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        raise ExtractError("Không đọc được bảng mã của tệp văn bản. Hãy lưu dạng UTF-8.")
    if name.endswith(".docx"):
        try:
            import docx  # python-docx
        except ImportError as exc:  # pragma: no cover
            raise ExtractError("Thiếu thư viện python-docx.") from exc
        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ExtractError("Không mở được tệp Word.") from exc
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(parts)
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise ExtractError("Thiếu thư viện pypdf.") from exc
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            raise ExtractError("Không đọc được tệp PDF.") from exc
        if not text.strip():
            raise ExtractError("Tệp PDF không có lớp chữ (có thể là ảnh scan). Hãy dán nội dung dạng văn bản.")
        return text
    raise ExtractError("Chỉ hỗ trợ tệp .txt, .md, .docx, .pdf.")


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = re.sub(r"[  ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Cắt đoạn
# ---------------------------------------------------------------------------


def _sentences(paragraph: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…;])\s+", paragraph)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Cắt văn bản thành các đoạn ≤ max_chars, ưu tiên ranh giới đoạn văn rồi đến câu."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean_text(text)) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        pieces = [para] if len(para) <= max_chars else _sentences(para)
        for piece in pieces:
            while len(piece) > max_chars:  # câu quá dài: cắt cứng
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(piece[:max_chars])
                piece = piece[max_chars:]
            candidate = f"{current}\n{piece}" if current else piece
            if len(candidate) > max_chars and current:
                chunks.append(current)
                current = piece
            else:
                current = candidate
        # giữ đoạn ngắn đi liền với đoạn sau (thường là tiêu đề)
        if len(current) >= max_chars * 0.5:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def reindex_material(db: Session, material: Material) -> int:
    """Cắt lại đoạn cho tài liệu. Tài liệu chưa duyệt sẽ bị gỡ khỏi chỉ mục."""
    for old in list(material.chunks):
        material.chunks.remove(old)  # delete-orphan: xóa khỏi CSDL khi flush
    db.flush()
    if not material.is_approved:
        return 0
    pieces = chunk_text(material.content)
    for i, piece in enumerate(pieces):
        material.chunks.append(
            Chunk(course_id=material.course_id, topic_id=material.topic_id, position=i, text=piece)
        )
    db.flush()
    return len(pieces)


def approve_material(db: Session, material: Material, approved: bool = True) -> int:
    material.status = "approved" if approved else "pending"
    material.approved_at = utcnow() if approved else None
    db.flush()
    return reindex_material(db, material)


# ---------------------------------------------------------------------------
# Tra cứu BM25
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    syllables = [w for w in re.findall(r"[a-z0-9_]+", norm(text)) if w not in STOPWORDS]
    bigrams = [f"{a}_{b}" for a, b in pairwise(syllables)]
    return syllables + bigrams


@dataclass
class Hit:
    chunk: Chunk
    score: float

    @property
    def title(self) -> str:
        return self.chunk.material.title if self.chunk.material else "Tài liệu"


def retrieve(
    db: Session,
    course_id: int,
    query: str,
    topic_id: int | None = None,
    k: int = 3,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[Hit]:
    chunks = list(
        db.scalars(
            select(Chunk)
            .join(Material, Chunk.material_id == Material.id)
            .where(Chunk.course_id == course_id, Material.status == "approved")
        ).all()
    )
    if not chunks:
        return []
    q_tokens = set(tokenize(query))
    docs = [Counter(tokenize(c.text)) for c in chunks]
    n = len(docs)
    avg_len = sum(sum(d.values()) for d in docs) / n or 1.0
    df: Counter = Counter()
    for d in docs:
        df.update(d.keys())
    hits: list[Hit] = []
    for chunk, d in zip(chunks, docs, strict=True):
        length = sum(d.values()) or 1
        score = 0.0
        for t in q_tokens:
            tf = d.get(t)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            weight = 1.5 if "_" in t else 1.0  # cụm hai âm tiết khớp có giá trị hơn
            score += weight * idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_len))
        if topic_id is not None and chunk.topic_id == topic_id:
            score = score * 1.6 + 0.5  # ưu tiên tài liệu đúng chủ đề
        if score > 0:
            hits.append(Hit(chunk, score))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
