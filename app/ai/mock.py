"""Chế độ demo: AI theo luật, không gọi mô hình thật.

Dùng khi chưa cấu hình GEMINI_API_KEY và trong kiểm thử. Gợi ý được dựng từ lời giải mẫu của giáo viên
(mỗi dòng một bước) và tài liệu đã duyệt, nên vẫn thể hiện đúng bậc thang gợi ý:
mức 1 câu hỏi định hướng → mức 2 nhắc kiến thức → mức 3 bước đầu → mức 4 các bước trung gian.
"""

from __future__ import annotations

import random
import re

from ..utils.text import norm
from .base import AIProvider
from .schemas import (
    AskRequest,
    AskResult,
    GeneratedQuestion,
    HintRequest,
    HintResult,
    JudgeRequest,
    JudgeResult,
    QuestionGenRequest,
    Snippet,
    SolutionRequest,
    SolutionResult,
    TutorContext,
)

ASK_FOR_ANSWER = ("dap an", "lam ho", "giai ho", "giai giup", "loi giai", "ket qua la", "cho em ket qua", "chon cau nao")


def _to_float(text: str) -> float | None:
    cleaned = (text or "").strip().replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def working_steps(steps: list[str]) -> list[str]:
    """Các bước lời giải, bỏ dòng 'Đáp án: ...' cuối cùng."""
    return [s for s in steps if not norm(s).startswith(("dap an", "ket luan", "vay dap an"))]


def best_sentences(snippets: list[Snippet], query: str, limit: int = 2) -> tuple[str, list[int]]:
    """Chọn 1–2 câu trong tài liệu khớp nhất với đề bài."""
    from ..services.knowledge import tokenize

    q = set(tokenize(query))
    scored: list[tuple[float, str, int]] = []
    for rank, sn in enumerate(snippets):
        weight = 1.0 / (1 + 0.6 * rank)  # đoạn tài liệu xếp hạng cao (đúng chủ đề) được ưu tiên
        for sentence in re.split(r"(?<=[.!?])\s+|\n", sn.text):
            sentence = sentence.strip(" -•\t")
            if len(sentence) < 25:
                continue
            words = set(tokenize(sentence))
            overlap = len(q & words) / (len(words) ** 0.5 or 1)
            if overlap > 0:
                scored.append((overlap * weight, sentence, sn.id))
    if not scored:
        return "", []
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][0]
    picked = [x for x in scored[:limit] if x[0] >= best * 0.6]
    return " ".join(s for _, s, _ in picked), sorted({i for _, _, i in picked})


class MockProvider(AIProvider):
    name = "demo"
    is_real = False

    # ------------------------------------------------------------------
    def diagnose(self, req: HintRequest) -> str:
        msg = norm(req.student_message)
        if any(k in msg for k in ("khong hieu de", "de hoi", "yeu cau gi", "khong hieu cau", "de bai")):
            return "chua_hieu_de"
        if any(k in msg for k in ("la gi", "khong nho", "quen", "khai niem", "cu phap", "khong biet lenh")):
            return "thieu_kien_thuc"
        if req.student_answers:
            last = _to_float(req.student_answers[-1])
            ref = _to_float(req.reference_answer.split("\n")[0])
            if last is not None and ref is not None and (abs(last - ref) <= 2 or abs(last - ref) <= abs(ref) * 0.2):
                return "sai_sot"
            return "sai_phuong_phap"
        if len(msg) < 25 or any(k in msg for k in ("khong biet", "bat dau", "lam sao", "the nao")):
            return "chua_bat_dau"
        return "sai_phuong_phap"

    def _level1(self, kind: str, topic: str) -> str:
        return {
            "chua_hieu_de": (
                "Mình cùng đọc kỹ đề nhé. Đề bài yêu cầu em tìm (hoặc viết) điều gì? Em thử gạch chân các dữ kiện "
                f"quan trọng và cho biết chúng liên quan đến kiến thức nào trong chủ đề “{topic}”."
            ),
            "chua_bat_dau": (
                "Em đừng lo, mình bắt đầu từ điều em đã biết. Đề bài cho những gì và cần tìm gì? "
                f"Trong chủ đề “{topic}”, kiến thức nào giúp em nối hai điều đó với nhau?"
            ),
            "thieu_kien_thuc": (
                f"Câu này dùng kiến thức của chủ đề “{topic}”. Em nhớ lại xem trong bài học có khái niệm hay câu lệnh "
                "nào liên quan trực tiếp đến yêu cầu của đề? Em thử viết ra điều em nhớ được nhé."
            ),
            "sai_sot": (
                "Hướng làm của em có vẻ gần đúng rồi. Em thử thực hiện lại từng bước thật cẩn thận, ghi kết quả "
                "của mỗi bước ra giấy. Sai lệch xuất hiện ở bước nào?"
            ),
        }.get(
            kind,
            "Em đã có hướng làm, tốt lắm. Em kiểm tra lại xem cách làm đã đáp ứng đúng yêu cầu của đề chưa? "
            "Có dữ kiện nào trong đề em chưa dùng đến không?",
        )

    def hint(self, req: HintRequest) -> HintResult:
        kind = self.diagnose(req)
        steps = working_steps(req.reference_solution)
        sources: list[int] = []
        if req.level <= 1:
            text = self._level1(kind, req.topic_name)
        elif req.level == 2:
            snippet, sources = best_sentences(req.materials, req.question_text)
            if snippet:
                text = f"Nhắc lại kiến thức: {snippet}\nEm thử áp dụng điều này vào đề bài: bước đầu tiên em sẽ làm gì?"
            else:
                text = (
                    f"Em xem lại phần lý thuyết của chủ đề “{req.topic_name}”: khái niệm nào được dùng trong đề bài? "
                    "Em viết lại khái niệm đó bằng lời của mình rồi thử áp dụng nhé."
                )
        elif req.level == 3:
            first = steps[0] if steps else "Xác định rõ dữ kiện đã cho và điều cần tìm."
            extra = " Em so sánh với cách em đã làm xem khác nhau ở đâu." if req.student_answers else ""
            text = f"Gợi ý cách làm: {first}{extra}\nEm thử làm tiếp từ bước này nhé?"
        else:
            shown = steps[:-1] if len(steps) > 1 else steps[:1]
            body = "\n".join(f"{i}. {s}" for i, s in enumerate(shown, 1))
            text = f"Mình cùng làm từng bước nhé:\n{body}\nBước cuối cùng em tự hoàn thành và nhập đáp án nhé!"
        analysis = {
            "chua_hieu_de": "Học sinh chưa xác định được yêu cầu của đề.",
            "chua_bat_dau": "Học sinh chưa biết bắt đầu từ đâu.",
            "thieu_kien_thuc": "Học sinh chưa nắm vững kiến thức liên quan.",
            "sai_phuong_phap": "Học sinh đã có hướng làm nhưng chưa đúng.",
            "sai_sot": "Học sinh làm gần đúng, có sai sót nhỏ.",
        }.get(kind, "Chưa xác định rõ khó khăn.")
        return HintResult(difficulty_type=kind, analysis=analysis, hint=text, source_ids=sources)

    # ------------------------------------------------------------------
    def _full_solution(self, ctx: TutorContext) -> str:
        steps = working_steps(ctx.reference_solution)
        body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) if steps else "(Giáo viên chưa nhập lời giải mẫu.)"
        return f"Lời giải:\n{body}\nĐáp án: {ctx.reference_answer or '(chưa có)'}"

    def ask(self, req: AskRequest) -> AskResult:
        msg = norm(req.student_message)
        if req.mode == "direct":
            return AskResult(reply=self._full_solution(req))
        if any(k in msg for k in ASK_FOR_ANSWER):
            return AskResult(
                reply=(
                    "Mình không đưa đáp án ngay đâu, vì em hoàn toàn có thể tự làm được! "
                    "Em cho mình biết: em đã làm đến bước nào và đang vướng ở đâu?"
                )
            )
        snippet, sources = best_sentences(req.materials, req.student_message)
        if snippet and req.level_cap >= 2:
            return AskResult(
                reply=f"Theo tài liệu của thầy cô: {snippet}\nEm thử dùng ý này cho bài đang làm xem sao?",
                source_ids=sources,
            )
        return AskResult(
            reply=(
                "Câu hỏi hay đó! Em thử nghĩ: điều em hỏi liên quan đến dữ kiện nào trong đề? "
                "Em viết ra suy nghĩ của mình, mình sẽ cùng em kiểm tra."
            )
        )

    def solution(self, req: SolutionRequest) -> SolutionResult:
        text = self._full_solution(req)
        if req.adaptive:
            text += "\nBây giờ em che lời giải lại và tự làm lại một lần nhé, như vậy em sẽ nhớ lâu hơn."
        return SolutionResult(solution=text)

    def judge(self, req: JudgeRequest) -> JudgeResult:
        ref_words = set(re.findall(r"[a-z0-9_]+", norm(req.reference_answer)))
        ans_words = set(re.findall(r"[a-z0-9_]+", norm(req.student_answer)))
        if not ref_words:
            return JudgeResult(correct=False, feedback="Chưa có đáp án tham khảo để so sánh.")
        overlap = len(ref_words & ans_words) / len(ref_words)
        ok = overlap >= 0.6
        return JudgeResult(
            correct=ok,
            feedback="Câu trả lời đã nêu được các ý chính." if ok else "Câu trả lời còn thiếu ý chính so với yêu cầu.",
        )

    # ------------------------------------------------------------------
    def generate_questions(self, req: QuestionGenRequest) -> list[GeneratedQuestion]:
        """Sinh câu điền khuyết đơn giản từ các câu định nghĩa dạng “X là Y” trong tài liệu."""
        pairs: list[tuple[str, str]] = []
        for sentence in re.split(r"(?<=[.!?])\s+|\n", req.material_text):
            sentence = sentence.strip(" -•\t")
            m = re.match(r"^(.{3,60}?)\s+là\s+(.{15,220})$", sentence)
            if m and len(m.group(1).split()) <= 8:
                pairs.append((m.group(1).strip(), m.group(2).strip().rstrip(".")))
        rng = random.Random(len(req.material_text))
        rng.shuffle(pairs)
        out: list[GeneratedQuestion] = []
        subjects = [s for s, _ in pairs]
        for i, (subject, predicate) in enumerate(pairs[: req.count]):
            use_mcq = req.kind == "mcq" or (req.kind == "mixed" and i % 2 == 0)
            distractors = [s for s in subjects if s != subject][:3]
            if use_mcq and len(distractors) == 3:
                options = [subject, *distractors]
                rng.shuffle(options)
                out.append(
                    GeneratedQuestion(
                        kind="mcq",
                        stem=f"Khái niệm nào được mô tả như sau: “… là {predicate}”?",
                        options=options,
                        correct_option=options.index(subject),
                        solution_steps=[f"Theo tài liệu: {subject} là {predicate}.", f"Đáp án: {subject}"],
                        difficulty=req.difficulty,
                    )
                )
            else:
                out.append(
                    GeneratedQuestion(
                        kind="short",
                        stem=f"Điền vào chỗ trống: “…………… là {predicate}.”",
                        answer=subject,
                        solution_steps=[f"Theo tài liệu: {subject} là {predicate}.", f"Đáp án: {subject}"],
                        difficulty=req.difficulty,
                    )
                )
        return out
