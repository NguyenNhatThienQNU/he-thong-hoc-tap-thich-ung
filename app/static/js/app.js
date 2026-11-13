/* Tương tác chung */
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  window.APP = { csrf };

  // Hỏi xác nhận trước khi gửi form nguy hiểm; hiện trạng thái "đang xử lý" cho form chạy lâu
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    if (form.dataset.loading) {
      const buttons = form.querySelectorAll("button");
      const last = buttons[buttons.length - 1];
      setTimeout(() => {
        buttons.forEach((b) => (b.disabled = true));
        if (last) last.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${form.dataset.loading}`;
      }, 0);
    }
  });

  // Tự gửi form khi đổi lựa chọn (vd. đổi nhóm của học sinh)
  document.querySelectorAll("select[data-autosubmit]").forEach((sel) =>
    sel.addEventListener("change", () => sel.form.submit())
  );

  // Bấm cả dòng bảng để mở chi tiết
  document.querySelectorAll(".clickable-row").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, form, input, select, label")) return;
      window.location.href = row.dataset.href;
    });
  });

  // Chọn / bỏ chọn tất cả
  document.querySelectorAll("[data-check-all]").forEach((box) =>
    box.addEventListener("change", () =>
      document.querySelectorAll(`input[name="${box.dataset.checkAll}"]`).forEach((c) => (c.checked = box.checked))
    )
  );

  // Form câu hỏi: ẩn/hiện phần trắc nghiệm hoặc đáp án ngắn theo loại câu
  const kindSelect = document.getElementById("kindSelect");
  if (kindSelect) {
    const update = () => {
      const mcq = kindSelect.value === "mcq";
      document.querySelectorAll(".only-mcq").forEach((el) => el.classList.toggle("d-none", !mcq));
      document.querySelectorAll(".only-text").forEach((el) => el.classList.toggle("d-none", mcq));
    };
    kindSelect.addEventListener("change", update);
    update();
  }
})();
