"""Lời nhắc (prompt) cho mô hình AI. Viết bằng tiếng Việt, tách riêng để dễ chỉnh và báo cáo trong đề tài."""

from __future__ import annotations

from .schemas import AskRequest, HintRequest, JudgeRequest, QuestionGenRequest, SolutionRequest, TutorContext

LEVEL_INSTRUCTIONS = {
    1: (
        "Chỉ đặt 1–2 câu hỏi gợi mở giúp em tự xác định: đề hỏi gì, đã cho dữ kiện gì, liên quan đến "
        "kiến thức nào. KHÔNG nêu công thức, quy tắc hay cách làm."
    ),
    2: (
        "Nhắc lại ngắn gọn khái niệm, quy tắc hoặc cú pháp liên quan, lấy từ tài liệu của giáo viên (1–3 câu), "
        "rồi hỏi em sẽ áp dụng vào bài như thế nào. KHÔNG áp dụng hộ vào bài."
    ),
    3: (
        "Gợi ý hướng giải hoặc nêu bước đầu tiên cần làm; có thể chỉ ra chỗ em đang làm chưa đúng. "
        "KHÔNG thực hiện các bước, KHÔNG tính ra kết quả."
    ),
    4: (
        "Hướng dẫn chi tiết các bước trung gian (hoặc giải một ví dụ tương tự với số liệu khác), dừng lại "
        "trước bước cuối cùng để em tự hoàn thành. KHÔNG nêu kết quả cuối cùng."
    ),
}


def adaptive_system(subject: str) -> str:
    return f"""Bạn là "AI Gợi Mở", gia sư AI cho học sinh THPT Việt Nam, môn {subject}.
Bạn hướng dẫn theo phương pháp hỗ trợ thích ứng (scaffolding): giúp học sinh TỰ tìm ra lời giải, không làm thay.

Quy tắc bắt buộc:
1. Tuyệt đối không nêu đáp án cuối cùng, không chọn hộ phương án trắc nghiệm, không viết lời giải hoàn chỉnh,
   không viết sẵn đoạn mã hay biểu thức trả lời trọn vẹn câu hỏi.
2. Chỉ hỗ trợ đúng MỨC GỢI Ý được yêu cầu, không vượt mức.
3. Kiến thức phải bám sát TÀI LIỆU CỦA GIÁO VIÊN được cung cấp. Dùng đoạn tài liệu nào thì ghi id của đoạn đó
   vào source_ids. Không đưa kiến thức ngoài tài liệu và chương trình phổ thông.
4. Ngắn gọn (tối đa khoảng 90 từ), dễ hiểu, giọng thân thiện, gọi học sinh là "em".
5. Ghi nhận cụ thể điều em đã làm đúng (nếu có), không chê bai.
6. Luôn kết thúc bằng một câu hỏi hoặc một yêu cầu nhỏ để em tự làm bước tiếp theo.
7. Viết văn bản thuần; có thể đặt tên lệnh trong dấu `...`; không dùng tiêu đề markdown."""


def direct_system(subject: str) -> str:
    return f"""Bạn là trợ lý AI giải bài tập môn {subject} cho học sinh THPT Việt Nam.
Khi học sinh hỏi, hãy trả lời trực tiếp và đầy đủ: trình bày lời giải từng bước rõ ràng và nêu đáp án cuối cùng.
Bám sát tài liệu của giáo viên nếu có. Viết ngắn gọn, dễ hiểu, gọi học sinh là "em"."""


def _context_block(ctx: TutorContext, reveal_reference: bool = True) -> str:
    lines = [f"CHỦ ĐỀ: {ctx.topic_name}", "ĐỀ BÀI:", ctx.question_text.strip(), ""]
    if reveal_reference:
        lines.append("ĐÁP ÁN VÀ LỜI GIẢI THAM KHẢO CỦA GIÁO VIÊN (bí mật – chỉ để bạn hiểu bài, không tiết lộ):")
        lines.append(f"- Đáp án: {ctx.reference_answer or '(không có)'}")
        if ctx.reference_solution:
            lines.append("- Lời giải:")
            lines += [f"  {i}. {step}" for i, step in enumerate(ctx.reference_solution, 1)]
        lines.append("")
    pct = round(ctx.mastery * 100)
    lines.append(f"MỨC NẮM VỮNG CHỦ ĐỀ HIỆN TẠI CỦA EM (ước lượng): {pct}%")
    if ctx.student_answers:
        lines.append("CÁC LẦN TRẢ LỜI CHƯA ĐÚNG CỦA EM:")
        lines += [f"- {a}" for a in ctx.student_answers[-4:]]
    if ctx.history:
        lines.append("HỘI THOẠI GẦN ĐÂY:")
        for role, text in ctx.history[-6:]:
            who = "Em" if role == "student" else "AI"
            lines.append(f"- {who}: {text.strip()[:600]}")
    lines.append("")
    lines.append("TÀI LIỆU CỦA GIÁO VIÊN:")
    if ctx.materials:
        for sn in ctx.materials:
            lines.append(f"[id={sn.id}] ({sn.title}) {sn.text.strip()}")
    else:
        lines.append("(không tìm thấy đoạn tài liệu phù hợp – chỉ dùng kiến thức cơ bản trong chương trình)")
    return "\n".join(lines)


def hint_prompt(req: HintRequest) -> str:
    return (
        _context_block(req)
        + f"""

EM VỪA VIẾT (hướng làm hoặc chỗ đang vướng): "{req.student_message.strip() or '(em chưa viết gì)'}"
Loại khó khăn đã ghi nhận lần trước: {req.previous_difficulty or '(chưa có)'}

NHIỆM VỤ:
1. Chẩn đoán khó khăn chính của em, chọn difficulty_type trong: chua_hieu_de (chưa hiểu yêu cầu đề),
   chua_bat_dau (chưa biết bắt đầu), thieu_kien_thuc (chưa nắm kiến thức), sai_phuong_phap (chọn sai hướng),
   sai_sot (sai sót nhỏ khi tính toán, cú pháp), khac.
2. analysis: một câu nhận định ngắn cho giáo viên.
3. hint: viết lời gợi ý đúng MỨC {req.level} – {req.level_name}. {req.level_instruction}"""
    )


def ask_prompt(req: AskRequest) -> str:
    if req.mode == "direct":
        return (
            _context_block(req)
            + f"""

CÂU HỎI CỦA EM: "{req.student_message.strip()}"
Hãy trả lời trực tiếp, đầy đủ câu hỏi của em (được phép nêu lời giải và đáp án). Ghi id tài liệu đã dùng vào source_ids."""
        )
    level_text = LEVEL_INSTRUCTIONS.get(min(max(req.level_cap, 1), 4), LEVEL_INSTRUCTIONS[2])
    return (
        _context_block(req)
        + f"""

CÂU HỎI CỦA EM: "{req.student_message.strip()}"
Hãy trả lời câu hỏi của em theo đúng quy tắc gia sư gợi mở. Mức hỗ trợ tối đa cho phép lúc này là mức {req.level_cap}:
{level_text}
Nếu em hỏi thẳng đáp án hoặc nhờ làm hộ, hãy từ chối nhẹ nhàng và đưa một câu hỏi gợi mở thay thế.
Nếu em hỏi một khái niệm, hãy giải thích khái niệm đó (dựa vào tài liệu) mà không áp dụng vào bài."""
    )


def solution_prompt(req: SolutionRequest) -> str:
    tail = (
        "Trình bày lời giải đầy đủ từng bước, nêu rõ đáp án cuối cùng ở dòng cuối dạng 'Đáp án: ...'. "
        "Sau lời giải, thêm một câu khuyến khích em che lời giải và tự làm lại một lần."
        if req.adaptive
        else "Trình bày lời giải đầy đủ từng bước và nêu rõ đáp án cuối cùng ở dòng cuối dạng 'Đáp án: ...'."
    )
    return _context_block(req) + "\n\nNHIỆM VỤ: " + tail + " Lời giải phải khớp với đáp án tham khảo của giáo viên."


def judge_system() -> str:
    return (
        "Bạn là giáo viên chấm câu trả lời của học sinh THPT. Chấm khách quan, chấp nhận cách viết tương đương "
        "(khác định dạng, cách đặt dấu cách, đơn vị đi kèm, thứ tự hợp lệ). Phản hồi bằng tiếng Việt."
    )


def judge_prompt(req: JudgeRequest) -> str:
    steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(req.reference_solution, 1))
    return f"""ĐỀ BÀI:
{req.question_text.strip()}

ĐÁP ÁN THAM KHẢO: {req.reference_answer}
LỜI GIẢI THAM KHẢO:
{steps or '  (không có)'}

CÂU TRẢ LỜI CỦA HỌC SINH: "{req.student_answer.strip()}"

Hãy cho biết câu trả lời có đúng (correct) không. feedback: một câu nhận xét ngắn, KHÔNG được nêu đáp án đúng."""


def question_system(subject: str) -> str:
    return (
        f"Bạn là giáo viên {subject} THPT giàu kinh nghiệm, soạn câu hỏi luyện tập bám sát tài liệu, "
        "chính xác về chuyên môn, diễn đạt rõ ràng bằng tiếng Việt."
    )


def question_prompt(req: QuestionGenRequest) -> str:
    kinds = {
        "mcq": "trắc nghiệm 4 phương án (kind = mcq)",
        "short": "trả lời ngắn (kind = short)",
        "mixed": "đan xen trắc nghiệm 4 phương án (mcq) và trả lời ngắn (short)",
    }.get(req.kind, "đan xen trắc nghiệm và trả lời ngắn")
    levels = {1: "Nhận biết", 2: "Thông hiểu", 3: "Vận dụng", 4: "Vận dụng cao"}
    return f"""Soạn {req.count} câu hỏi {kinds}, mức độ {levels.get(req.difficulty, 'Thông hiểu')} (difficulty = {req.difficulty}),
chủ đề "{req.topic_name}", dựa HOÀN TOÀN trên tài liệu dưới đây.

Yêu cầu:
- Trắc nghiệm: đúng 4 phương án, chỉ 1 phương án đúng; correct_option là chỉ số 0–3; các phương án nhiễu hợp lý.
- Trả lời ngắn: answer là đáp án ngắn gọn (một số, một từ, một biểu thức hoặc một dòng lệnh). Nếu có nhiều cách
  viết đúng, ghi mỗi cách trên một dòng.
- solution_steps: 2–5 bước giải ngắn, bước cuối có dạng "Đáp án: ...".
- Không trùng lặp ý giữa các câu.

TÀI LIỆU:
{req.material_text.strip()[:12000]}"""
