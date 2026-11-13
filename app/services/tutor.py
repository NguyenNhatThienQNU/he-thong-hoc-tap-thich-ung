"""Gia sư AI trong phiên luyện tập.

Hai chế độ được so sánh trong thực nghiệm:
- adaptive (nhóm thực nghiệm): AI chẩn đoán khó khăn, gợi ý theo bậc thang 4 mức và giảm dần hỗ trợ khi
  học sinh tiến bộ; lời giải chi tiết (mức 5) chỉ mở khi học sinh đã thử đủ số lần.
- direct (nhóm đối chứng): AI đưa lời giải trực tiếp ngay khi học sinh hỏi, giống cách dùng chatbot phổ biến.

Mọi tương tác được ghi vào bảng messages để phân tích "mức độ cần hỗ trợ từ AI".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..ai.base import AIError, AIProvider
from ..ai.mock import MockProvider
from ..ai.prompts import LEVEL_INSTRUCTIONS
from ..ai.schemas import AskRequest, HintRequest, HintResult, JudgeRequest, Snippet, SolutionRequest
from ..models import HINT_LEVELS, MODE_DIRECT, Message, PracticeSession, Question
from ..utils.md import render_md
from ..utils.text import OPTION_LETTERS, norm, option_letter
from ..utils.timeutil import fmt_local, utcnow
from .knowledge import retrieve
from .mastery import SOLID, WEAK, apply_evidence, get_mastery, session_credit

log = logging.getLogger(__name__)
FALLBACK = MockProvider()
MIN_THINKING_CHARS = 15


class TutorError(ValueError):
    """Thao tác không hợp lệ (phiên đã kết thúc, dữ liệu trống...)."""


# ---------------------------------------------------------------------------
# Kiểm tra đáp án
# ---------------------------------------------------------------------------


def normalize_answer(text: str | None) -> str:
    t = norm(text).replace("“", '"').replace("”", '"').replace("'", '"')
    t = re.sub(r"\s+", "", t)
    return t.strip(".;")


def to_number(text: str | None) -> float | None:
    t = (text or "").strip().replace(" ", "")
    m = re.match(r"^[a-zA-Z_]\w*=(.+)$", t)  # "x = 5" -> 5
    if m:
        t = m.group(1)
    t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def parse_option(raw: str, n_options: int) -> int | None:
    raw = (raw or "").strip().upper()
    if len(raw) == 1 and raw in OPTION_LETTERS[:n_options]:
        return OPTION_LETTERS.index(raw)
    if raw.isdigit() and 0 <= int(raw) < n_options:
        return int(raw)
    return None


@dataclass
class CheckResult:
    correct: bool
    feedback: str = ""
    method: str = "exact"


def check_answer(ai: AIProvider, question: Question, raw: str, use_ai: bool = True) -> CheckResult:
    raw = (raw or "").strip()
    if question.kind == "mcq":
        idx = parse_option(raw, len(question.options_list))
        return CheckResult(idx is not None and idx == question.correct_option, method="option")
    if not raw:
        return CheckResult(False, "Em chưa nhập câu trả lời.")
    accepted = question.accepted_answers
    target = normalize_answer(raw)
    if any(normalize_answer(a) == target for a in accepted):
        return CheckResult(True, method="exact")
    num = to_number(raw)
    ref_nums = [n for n in (to_number(a) for a in accepted) if n is not None]
    if num is not None and ref_nums:
        ok = any(abs(num - r) <= 1e-6 + 1e-4 * abs(r) for r in ref_nums)
        return CheckResult(ok, method="numeric")
    if not use_ai or not accepted:
        return CheckResult(False)
    request = JudgeRequest(
        question_text=question.as_text(),
        kind=question.kind,
        reference_answer="\n".join(accepted),
        reference_solution=question.solution_steps,
        student_answer=raw,
    )
    provider = ai if (ai.is_real or question.kind == "open") else None
    if provider is None:
        return CheckResult(False)
    try:
        result = provider.judge(request)
    except AIError as exc:
        log.warning("Không chấm được bằng AI: %s", exc)
        result = FALLBACK.judge(request)
    feedback = result.feedback if not leaks_answer(result.feedback, question) else ""
    return CheckResult(result.correct, feedback, method="ai")


# ---------------------------------------------------------------------------
# Chặn lộ đáp án trong gợi ý
# ---------------------------------------------------------------------------


def leaks_answer(text: str | None, question: Question) -> bool:
    t = norm(text)
    if not t:
        return False
    if question.kind == "mcq":
        letter = option_letter(question.correct_option).lower()
        pattern = rf"(dap an|chon|phuong an|cau tra loi)\s*(dung\s*)?(la\s*)?(:\s*)?\(?{letter}\b"
        return bool(re.search(pattern, t))
    for answer in question.accepted_answers:
        a = norm(answer).strip()
        if not a:
            continue
        if re.fullmatch(r"[a-z0-9]+(\.[0-9]+)?", a):
            # Đáp án là một số hoặc một từ (vd. 14, False, Kha): chỉ coi là lộ khi được nêu như kết quả
            pattern = rf"(dap an|ket qua|bang|la|=|in ra|se in|thu duoc|nhan gia tri|gia tri cua no)\s*:?\s*{re.escape(a)}(?![a-z0-9])"
            if re.search(pattern, t):
                return True
        elif len(a) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", t):
            return True  # đáp án dạng mã lệnh, biểu thức: xuất hiện nguyên văn là lộ
    return False


def redact(text: str, question: Question) -> str:
    """Bỏ các câu làm lộ đáp án, giữ lại phần gợi ý an toàn."""
    kept = []
    for line in (text or "").split("\n"):
        parts = re.split(r"(?<=[.!?])\s+", line)
        safe = [p for p in parts if p.strip() and not leaks_answer(p, question)]
        if safe:
            kept.append(" ".join(safe))
    return "\n".join(kept).strip()


# ---------------------------------------------------------------------------
# Chính sách gợi ý thích ứng
# ---------------------------------------------------------------------------


def start_level(p: float, difficulty_type: str | None) -> int:
    """Mức gợi ý đầu tiên: học sinh còn yếu và thiếu kiến thức được nhắc kiến thức ngay (mức 2)."""
    if difficulty_type == "sai_sot":
        return 1
    if p < WEAK and difficulty_type in ("thieu_kien_thuc", "chua_bat_dau"):
        return 2
    return 1


def hint_ceiling(policy: dict, p: float, wrong_attempts: int) -> int:
    """Mức gợi ý tối đa hiện được phép (1–4). Giảm hỗ trợ khi học sinh đã nắm vững chủ đề."""
    if policy["fading"] and p >= SOLID and wrong_attempts < policy["min_attempts_for_solution"]:
        return max(1, min(4, int(policy["max_level_mastered"])))
    return 4


def can_view_solution(session: PracticeSession, policy: dict) -> tuple[bool, str]:
    if session.mode == MODE_DIRECT or session.solution_viewed:
        return True, ""
    need_attempts = int(policy["min_attempts_for_solution"])
    missing = []
    if session.wrong_attempts < need_attempts:
        missing.append(f"trả lời thêm {need_attempts - session.wrong_attempts} lần")
    if session.max_hint_level < 4:
        missing.append("xem gợi ý đến mức 4 (làm mẫu một phần)")
    if missing:
        return False, "Lời giải chi tiết sẽ mở khi em " + " và ".join(missing) + "."
    return True, ""


def preview_next_level(session: PracticeSession, policy: dict, p: float) -> int:
    if session.max_hint_level == 0:
        return start_level(p, session.last_difficulty)
    return min(session.max_hint_level + 1, hint_ceiling(policy, p, session.wrong_attempts))


# ---------------------------------------------------------------------------
# Ngữ cảnh gửi cho AI
# ---------------------------------------------------------------------------


def _context(db: Session, session: PracticeSession, extra_query: str = "") -> dict:
    q = session.question
    topic = q.topic
    hits = retrieve(db, q.course_id, f"{q.stem} {extra_query}", topic_id=q.topic_id, k=3)
    history = [(m.role, m.content) for m in session.messages if m.role in ("student", "ai")][-8:]
    wrong = [m.content for m in session.messages if m.kind == "answer" and (m.meta or {}).get("correct") is False]
    m = get_mastery(db, session.student_id, session.topic_id)
    return dict(
        subject_name=q.course.name,
        topic_name=topic.name if topic else "",
        question_text=q.as_text(),
        question_kind=q.kind,
        reference_answer=q.final_answer_text,
        reference_solution=q.solution_steps,
        student_answers=wrong,
        history=history,
        mastery=m.p_known,
        materials=[Snippet(id=h.chunk.id, title=h.title, text=h.chunk.text) for h in hits],
    )


def _source_titles(ctx: dict, ids: list[int]) -> list[str]:
    by_id = {s.id: s.title for s in ctx["materials"]}
    titles = []
    for i in ids or []:
        if i in by_id and by_id[i] not in titles:
            titles.append(by_id[i])
    return titles


# ---------------------------------------------------------------------------
# Nhật ký
# ---------------------------------------------------------------------------


def add_message(
    db: Session, session: PracticeSession, role: str, kind: str, content: str, level: int | None = None, **meta
) -> Message:
    msg = Message(session_id=session.id, role=role, kind=kind, level=level, content=content, meta=meta)
    db.add(msg)
    session.messages.append(msg)
    db.flush()
    return msg


def message_dict(m: Message) -> dict:
    meta = m.meta or {}
    return {
        "id": m.id,
        "role": m.role,
        "kind": m.kind,
        "level": m.level,
        "level_name": HINT_LEVELS[m.level][0] if m.level in HINT_LEVELS else "",
        "html": str(render_md(m.content)),
        "sources": meta.get("sources", []),
        "correct": meta.get("correct"),
        "time": fmt_local(m.created_at, "%H:%M"),
    }


def session_state(db: Session, session: PracticeSession) -> dict:
    policy = session.question.course.full_policy
    m = get_mastery(db, session.student_id, session.topic_id)
    allowed, requirement = can_view_solution(session, policy)
    nxt = preview_next_level(session, policy, m.p_known)
    return {
        "id": session.id,
        "mode": session.mode,
        "status": session.status,
        "status_label": session.status_label,
        "active": session.is_active,
        "attempts": session.attempts,
        "wrong_attempts": session.wrong_attempts,
        "hint_requests": session.hint_requests,
        "max_hint_level": session.max_hint_level,
        "solution_viewed": session.solution_viewed,
        "independent": session.independent,
        "can_view_solution": allowed,
        "solution_requirement": requirement,
        "next_level": nxt,
        "next_level_name": HINT_LEVELS[nxt][0],
        "hint_ceiling": hint_ceiling(policy, m.p_known, session.wrong_attempts),
        "wrong_options": list(session.wrong_options or []),
        "mastery_pct": round(m.p_known * 100),
        "p_before": round(session.p_before * 100) if session.p_before is not None else None,
        "p_after": round(session.p_after * 100) if session.p_after is not None else None,
    }


def _result(db: Session, session: PracticeSession, messages: list[Message], **extra) -> dict:
    return {"state": session_state(db, session), "messages": [message_dict(m) for m in messages], **extra}


# ---------------------------------------------------------------------------
# Các thao tác trong phiên
# ---------------------------------------------------------------------------


def _ensure_active(session: PracticeSession) -> None:
    if not session.is_active:
        raise TutorError("Phiên luyện tập này đã kết thúc.")


def finalize(db: Session, session: PracticeSession, solved: bool) -> None:
    session.status = "solved" if solved else "given_up"
    session.correct = solved
    session.ended_at = utcnow()
    session.independent = bool(solved and not session.solution_viewed and session.max_hint_level <= 1)
    credit = session_credit(session, session.question.kind)
    before, after = apply_evidence(db, session.student_id, session.topic_id, credit, session.question.kind)
    session.p_before, session.p_after = before, after


def submit_answer(db: Session, ai: AIProvider, session: PracticeSession, raw: str) -> dict:
    _ensure_active(session)
    q = session.question
    raw = (raw or "").strip()
    if not raw:
        raise TutorError("Em hãy nhập câu trả lời trước khi nộp.")
    if q.kind == "mcq":
        idx = parse_option(raw, len(q.options_list))
        if idx is None:
            raise TutorError("Em hãy chọn một phương án.")
        if idx in (session.wrong_options or []):
            raise TutorError("Em đã chọn phương án này rồi, hãy suy nghĩ thêm nhé.")
        display = f"{OPTION_LETTERS[idx]}. {q.options_list[idx]}"
    else:
        display = raw
    check = check_answer(ai, q, raw)
    out = [add_message(db, session, "student", "answer", display, correct=check.correct, method=check.method)]
    session.attempts += 1
    if check.correct:
        finalize(db, session, solved=True)
        if session.independent:
            text = "Chính xác! Em đã tự giải được câu này."
        elif session.solution_viewed:
            text = (
                "Đúng rồi. Vì em đã xem lời giải nên câu này chưa được tính là tự giải; "
                "hệ thống sẽ cho em gặp lại dạng bài này để luyện thêm."
            )
        else:
            text = (
                f"Chính xác! Em hoàn thành câu này với gợi ý đến mức {session.max_hint_level}. "
                "Lần sau em thử tự làm với ít gợi ý hơn nhé."
            )
        out.append(add_message(db, session, "ai", "feedback", text, correct=True))
    else:
        session.wrong_attempts += 1
        if q.kind == "mcq":
            session.wrong_options = [*(session.wrong_options or []), idx]
        text = "Chưa đúng."
        if check.feedback:
            text += " " + check.feedback
        if session.mode == MODE_DIRECT:
            text += " Em có thể thử lại, hoặc hỏi AI để xem lời giải."
        else:
            allowed, _ = can_view_solution(session, q.course.full_policy)
            text += " Em kiểm tra lại cách làm, hoặc bấm “Cần gợi ý” và viết chỗ em đang vướng."
            if allowed and not session.solution_viewed:
                text += " Em cũng đã có thể mở lời giải chi tiết."
        out.append(add_message(db, session, "ai", "feedback", text, correct=False))
    return _result(db, session, out)


def _last_index(session: PracticeSession, kinds: tuple[str, ...]) -> int:
    for i in range(len(session.messages) - 1, -1, -1):
        if session.messages[i].kind in kinds:
            return i
    return -1


def request_hint(db: Session, ai: AIProvider, session: PracticeSession, thinking: str = "") -> dict:
    _ensure_active(session)
    if session.mode == MODE_DIRECT:
        return view_solution(db, ai, session)
    q = session.question
    policy = q.course.full_policy
    thinking = (thinking or "").strip()
    answered_since_hint = _last_index(session, ("answer",)) > _last_index(session, ("hint", "reply", "solution"))
    if policy["require_attempt_first"] and len(thinking) < MIN_THINKING_CHARS and not answered_since_hint:
        return _result(
            db,
            session,
            [],
            need_thinking=True,
            prompt=(
                "Trước khi nhận gợi ý, em hãy viết ngắn gọn: em hiểu đề hỏi gì, đã thử làm gì "
                f"và đang vướng ở đâu (ít nhất {MIN_THINKING_CHARS} ký tự)."
            ),
        )
    out = [add_message(db, session, "student", "help", thinking or "(Em nhờ gợi ý)")]
    ctx = _context(db, session, thinking)
    p = ctx["mastery"]
    current = session.max_hint_level
    ceiling = hint_ceiling(policy, p, session.wrong_attempts)
    if current == 0:
        predicted = session.last_difficulty or FALLBACK.diagnose(
            HintRequest(**ctx, level=1, level_name="", level_instruction="", student_message=thinking)
        )
        level = start_level(p, predicted)
    else:
        level = current + 1
    capped = level > ceiling
    level = min(level, ceiling)
    request = HintRequest(
        **ctx,
        level=level,
        level_name=HINT_LEVELS[level][0],
        level_instruction=LEVEL_INSTRUCTIONS[level],
        student_message=thinking,
        previous_difficulty=session.last_difficulty,
    )
    meta: dict = {}
    try:
        result: HintResult = ai.hint(request)
    except AIError as exc:
        log.warning("AI gợi ý lỗi, dùng gợi ý theo luật: %s", exc)
        result = FALLBACK.hint(request)
        meta["ai_error"] = str(exc)
    if leaks_answer(result.hint, q):
        meta["leak_blocked"] = True
        safe_text, sources = redact(result.hint, q), result.source_ids
        if len(safe_text) < 40:
            fallback = FALLBACK.hint(request)
            safe_text, sources = redact(fallback.hint, q), fallback.source_ids
        if len(safe_text) < 40:  # không giữ được gợi ý an toàn ở mức này: lùi về câu hỏi định hướng
            safe_text, sources, level = FALLBACK._level1(result.difficulty_type, ctx["topic_name"]), [], min(level, 1)
        result = HintResult(
            difficulty_type=result.difficulty_type, analysis=result.analysis, hint=safe_text, source_ids=sources
        )
    out.append(
        add_message(
            db,
            session,
            "ai",
            "hint",
            result.hint,
            level=level,
            difficulty=result.difficulty_type,
            analysis=result.analysis,
            sources=_source_titles(ctx, result.source_ids),
            **meta,
        )
    )
    session.hint_requests += 1
    session.max_hint_level = max(current, level)
    session.last_difficulty = result.difficulty_type
    if capped and policy["fading"] and p >= SOLID:
        out.append(
            add_message(
                db,
                session,
                "system",
                "notice",
                (
                    f"Em đã nắm khá vững chủ đề này (khoảng {round(p * 100)}%), nên AI chỉ gợi ý tối đa mức {ceiling}. "
                    f"Em hãy thử trả lời: sau {policy['min_attempts_for_solution']} lần chưa đúng, "
                    "AI sẽ hỗ trợ nhiều hơn."
                ),
            )
        )
    return _result(db, session, out)


def ask(db: Session, ai: AIProvider, session: PracticeSession, text: str) -> dict:
    _ensure_active(session)
    text = (text or "").strip()
    if len(text) < 3:
        raise TutorError("Em hãy nhập câu hỏi.")
    q = session.question
    policy = q.course.full_policy
    out = [add_message(db, session, "student", "ask", text)]
    ctx = _context(db, session, text)
    if session.mode == MODE_DIRECT:
        request = AskRequest(**ctx, mode=MODE_DIRECT, student_message=text)
        try:
            result = ai.ask(request)
        except AIError as exc:
            log.warning("AI trả lời lỗi: %s", exc)
            result = FALLBACK.ask(request)
        reveals = leaks_answer(result.reply, q)
        level = 5 if reveals else 3
        out.append(
            add_message(db, session, "ai", "reply", result.reply, level=level, sources=_source_titles(ctx, result.source_ids))
        )
        session.hint_requests += 1
        session.max_hint_level = max(session.max_hint_level, level)
        if reveals:
            session.solution_viewed = True
        return _result(db, session, out)

    ceiling = hint_ceiling(policy, ctx["mastery"], session.wrong_attempts)
    cap = max(1, min(ceiling, max(2, session.max_hint_level)))
    request = AskRequest(**ctx, mode="adaptive", level_cap=cap, student_message=text)
    meta: dict = {}
    try:
        result = ai.ask(request)
    except AIError as exc:
        log.warning("AI trả lời lỗi: %s", exc)
        result = FALLBACK.ask(request)
        meta["ai_error"] = str(exc)
    if leaks_answer(result.reply, q):
        meta["leak_blocked"] = True
        safe_text = redact(result.reply, q)
        if len(safe_text) < 40:
            result = FALLBACK.ask(request)
            safe_text = redact(result.reply, q)
        if len(safe_text) < 40:
            safe_text, result.source_ids = (
                "Mình chưa thể nói điều đó lúc này. Em cho mình biết em đang làm đến bước nào nhé?",
                [],
            )
        result.reply = safe_text
    level = min(cap, 2) if result.source_ids else 1
    out.append(
        add_message(
            db, session, "ai", "reply", result.reply, level=level, sources=_source_titles(ctx, result.source_ids), **meta
        )
    )
    session.hint_requests += 1
    session.max_hint_level = max(session.max_hint_level, level)
    return _result(db, session, out)


def view_solution(db: Session, ai: AIProvider, session: PracticeSession) -> dict:
    _ensure_active(session)
    q = session.question
    allowed, requirement = can_view_solution(session, q.course.full_policy)
    if not allowed:
        return _result(db, session, [], denied=True, message=requirement)
    out = []
    if session.mode == MODE_DIRECT:
        out.append(add_message(db, session, "student", "help", "(Em hỏi AI lời giải)"))
    ctx = _context(db, session)
    request = SolutionRequest(**ctx, adaptive=session.mode != MODE_DIRECT)
    meta: dict = {}
    try:
        result = ai.solution(request)
    except AIError as exc:
        log.warning("AI lời giải lỗi: %s", exc)
        result = FALLBACK.solution(request)
        meta["ai_error"] = str(exc)
    out.append(add_message(db, session, "ai", "solution", result.solution, level=5, **meta))
    session.hint_requests += 1
    session.max_hint_level = 5
    session.solution_viewed = True
    return _result(db, session, out)


def give_up(db: Session, session: PracticeSession) -> dict:
    _ensure_active(session)
    out = [add_message(db, session, "system", "notice", "Em đã dừng câu này. Hệ thống sẽ cho em luyện lại dạng bài này sau.")]
    finalize(db, session, solved=False)
    return _result(db, session, out)
