/* Trang luyện tập: nộp đáp án, nhờ gợi ý theo bậc thang, hỏi AI, xem lời giải */
(function () {
  "use strict";
  const root = document.getElementById("practice");
  if (!root) return;
  const sid = root.dataset.session;
  const mode = root.dataset.mode;
  const kind = root.dataset.kind;
  const csrf = window.APP.csrf;
  let state = window.PRACTICE.state;
  let busy = false;

  const $ = (id) => document.getElementById(id);
  const chat = $("chat");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function renderMsg(m) {
    const div = document.createElement("div");
    let cls = `msg msg-${m.role} kind-${m.kind}`;
    if (m.correct === true) cls += " ok";
    else if (m.correct === false) cls += " bad";
    div.className = cls;
    const who = m.role === "student" ? "Em" : m.role === "ai" ? "AI Gợi Mở" : "";
    const level = m.role === "ai" && m.level ? ` · <span class="badge hint-badge hint-${m.level}">Mức ${m.level} · ${esc(m.level_name)}</span>` : "";
    const sources = m.sources && m.sources.length ? `<div><i class="bi bi-book"></i> Theo: ${m.sources.map(esc).join(", ")}</div>` : "";
    div.innerHTML = `<div class="bubble">${m.html}</div><div class="meta">${who ? who + " · " : ""}${esc(m.time)}${level}${sources}</div>`;
    chat.appendChild(div);
  }

  function showEmptyChat() {
    if (chat.children.length) return;
    const tip = mode === "direct"
      ? "Em hãy đọc đề và nộp câu trả lời. Nếu cần, bấm “Hỏi AI lời giải”."
      : "Em hãy thử tự làm trước. Khi vướng, bấm “Cần gợi ý” và viết ngắn gọn em đang vướng ở đâu, AI sẽ gợi ý từng bước.";
    chat.innerHTML = `<div class="text-center text-muted small py-4" id="chatTip"><i class="bi bi-lightbulb fs-3 d-block mb-2"></i>${tip}</div>`;
  }

  function scrollChat() {
    chat.scrollTop = chat.scrollHeight;
  }

  function typing(on) {
    let el = $("typing");
    if (on && !el) {
      el = document.createElement("div");
      el.id = "typing";
      el.className = "msg msg-ai";
      el.innerHTML = '<div class="bubble"><span class="typing"><span></span><span></span><span></span></span></div>';
      chat.appendChild(el);
      scrollChat();
    } else if (!on && el) {
      el.remove();
    }
  }

  function setBusy(on) {
    busy = on;
    root.querySelectorAll("button").forEach((b) => {
      if (on) {
        b.dataset.wasDisabled = b.disabled ? "1" : "";
        b.disabled = true;
      } else {
        b.disabled = b.dataset.wasDisabled === "1";
      }
    });
    typing(on);
    if (!on) updateUI();
  }

  async function call(path, body) {
    const res = await fetch(`/hs/api/phien/${sid}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body || {}),
    });
    let data;
    try {
      data = await res.json();
    } catch (e) {
      data = { detail: "Máy chủ chưa phản hồi được, em thử lại nhé." };
    }
    if (res.status === 401) window.location.href = "/hs/dang-nhap";
    if (!res.ok) throw new Error(data.detail || "Có lỗi xảy ra.");
    return data;
  }

  function apply(data) {
    $("chatTip")?.remove();
    (data.messages || []).forEach(renderMsg);
    if (data.state) state = data.state;
    scrollChat();
  }

  async function run(path, body, onData) {
    if (busy) return;
    $("answerError").textContent = "";
    setBusy(true);
    try {
      const data = await call(path, body);
      setBusy(false);
      if (onData && onData(data) === false) return;
      apply(data);
      updateUI();
    } catch (err) {
      setBusy(false);
      $("answerError").textContent = err.message;
    }
  }

  function updateUI() {
    if (busy) return;
    const pct = $("masteryPct");
    if (pct) pct.textContent = state.mastery_pct + "%";
    // Bậc thang gợi ý
    document.querySelectorAll(".rung").forEach((r) => {
      const lv = Number(r.dataset.level);
      r.classList.toggle("used", lv <= state.max_hint_level);
      r.classList.toggle("next", state.active && lv === state.next_level && lv > state.max_hint_level && lv <= 4);
      const locked = lv === 5 ? !state.can_view_solution : lv > state.hint_ceiling;
      r.classList.toggle("locked", state.active && locked && lv > state.max_hint_level);
    });
    const nextLabel = $("nextLabel");
    if (nextLabel) {
      nextLabel.textContent = state.active && state.max_hint_level < 4
        ? `Gợi ý tiếp theo: mức ${state.next_level}`
        : "";
    }
    const ceiling = $("ceilingNote");
    if (ceiling) {
      const capped = state.active && state.hint_ceiling < 4;
      ceiling.classList.toggle("d-none", !capped);
      if (capped) ceiling.innerHTML = `<i class="bi bi-graph-up-arrow"></i> Em đã nắm khá vững chủ đề này nên AI chỉ gợi ý tối đa mức ${state.hint_ceiling}. Hãy tin vào bản thân!`;
    }
    const solBtn = $("solutionBtn");
    if (solBtn) {
      solBtn.disabled = !state.active || state.solution_viewed;
      solBtn.innerHTML = state.can_view_solution
        ? '<i class="bi bi-unlock"></i> Xem lời giải'
        : '<i class="bi bi-lock"></i> Xem lời giải';
      solBtn.title = state.solution_requirement || "";
      $("solutionNote").textContent = state.active && !state.can_view_solution ? state.solution_requirement : "";
    }
    const hintBtn = $("hintBtn");
    if (hintBtn) {
      hintBtn.disabled = !state.active || (mode === "direct" && state.solution_viewed);
      if (mode !== "direct") hintBtn.disabled = hintBtn.disabled || (state.max_hint_level >= state.hint_ceiling && state.max_hint_level >= 4);
    }
    const giveUp = $("giveUpBtn");
    if (giveUp) giveUp.disabled = !state.active;
    // Trắc nghiệm: khóa các phương án đã chọn sai
    document.querySelectorAll(".option-btn").forEach((b) => {
      const idx = Number(b.dataset.index);
      b.disabled = !state.active || state.wrong_options.includes(idx);
    });
    const form = $("answerForm");
    if (form) form.querySelectorAll("input, textarea, button").forEach((el) => (el.disabled = !state.active));
    const askForm = $("askForm");
    askForm.querySelectorAll("input, button").forEach((el) => (el.disabled = !state.active));
    // Kết thúc
    if (!state.active) {
      document.querySelectorAll(".action-card").forEach((c) => c.classList.add("d-none"));
      const done = $("doneCard");
      done.classList.remove("d-none");
      let title, text;
      if (state.status === "given_up") {
        title = "Em đã dừng câu này";
        text = "Không sao cả! Hệ thống sẽ cho em gặp lại dạng bài này sau.";
      } else if (state.independent) {
        title = "Tuyệt vời, em đã tự giải được!";
        text = state.max_hint_level === 1 ? "Em chỉ cần một câu hỏi định hướng." : "Em không cần gợi ý nào.";
      } else if (state.solution_viewed) {
        title = "Em đã hoàn thành sau khi xem lời giải";
        text = "Lần sau em thử tự làm thêm một chút trước khi xem lời giải nhé.";
      } else {
        title = "Chính xác!";
        text = `Em hoàn thành với gợi ý đến mức ${state.max_hint_level}.`;
      }
      if (state.p_before !== null && state.p_after !== null) {
        text += ` Mức nắm vững chủ đề: ${state.p_before}% → ${state.p_after}%.`;
      }
      $("doneTitle").textContent = title;
      $("doneText").textContent = text;
      done.classList.toggle("not-indep", !state.independent);
    }
  }

  // Nộp đáp án
  document.querySelectorAll(".option-btn").forEach((b) =>
    b.addEventListener("click", () => run("tra-loi", { answer: b.dataset.index }))
  );
  const answerForm = $("answerForm");
  if (answerForm) {
    answerForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("answerInput");
      const value = input.value.trim();
      if (!value) return;
      run("tra-loi", { answer: value }, () => {
        input.value = "";
      });
    });
  }

  // Nhờ gợi ý (thích ứng) / hỏi lời giải (đối chứng)
  const thinkingBox = $("thinkingBox");
  function askHint(thinking) {
    run("goi-y", { thinking: thinking || "" }, (data) => {
      if (data.need_thinking && thinkingBox) {
        thinkingBox.classList.remove("d-none");
        $("thinkingPrompt").textContent = data.prompt;
        $("thinkingInput").focus();
        return false;
      }
      if (thinkingBox) {
        thinkingBox.classList.add("d-none");
        $("thinkingInput").value = "";
      }
      return true;
    });
  }
  $("hintBtn")?.addEventListener("click", () => {
    if (mode === "direct") return askHint("");
    const typed = $("thinkingInput").value.trim();
    if (!thinkingBox.classList.contains("d-none") && typed) return askHint(typed);
    askHint("");
  });
  $("thinkingSend")?.addEventListener("click", () => askHint($("thinkingInput").value.trim()));

  // Lời giải chi tiết (mức 5)
  $("solutionBtn")?.addEventListener("click", () => {
    if (!state.can_view_solution) {
      $("solutionNote").textContent = state.solution_requirement;
      return;
    }
    if (!window.confirm("Xem lời giải chi tiết? Câu này sẽ không được tính là tự giải.")) return;
    run("loi-giai", {}, (data) => {
      if (data.denied) {
        $("solutionNote").textContent = data.message;
        return false;
      }
      return true;
    });
  });

  // Bỏ qua
  $("giveUpBtn")?.addEventListener("click", () => {
    if (window.confirm("Dừng câu này? Em có thể luyện lại dạng bài này sau.")) run("bo-qua", {});
  });

  // Hỏi AI tự do
  $("askForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("askInput");
    const text = input.value.trim();
    if (!text) return;
    run("hoi", { text }, () => {
      input.value = "";
    });
  });

  window.PRACTICE.messages.forEach(renderMsg);
  showEmptyChat();
  scrollChat();
  updateUI();
  if (kind !== "mcq" && state.active) $("answerInput")?.focus();
})();
