# Trợ lý AI giúp học sinh nâng tầm tư duy – hệ thống hỗ trợ học tập thích ứng

Sản phẩm của đề tài: Nghiên cứu và phát triển Trợ lý AI giúp học sinh nâng tầm tư duy (hệ thống hỗ trợ học tập thích ứng) nhằm nâng cao năng lực tự học và hạn chế sự phụ thuộc vào AI của học sinh THPT.

AI không giải hộ. Học sinh viết chỗ đang vướng, AI chẩn đoán khó khăn và gợi ý theo bậc thang 5 mức, giảm dần hỗ trợ khi học sinh tiến bộ. Hệ thống có sẵn mô-đun thực nghiệm để so sánh với cách dùng AI cho lời giải trực tiếp.

## Chức năng

| Nhóm | Chức năng | Mã nguồn |
|---|---|---|
| Kho tri thức | Tải tài liệu (.docx, .pdf, .txt), giáo viên đọc, sửa, duyệt; tự cắt đoạn và tra cứu BM25; thử tra cứu ngay trên giao diện | `app/services/knowledge.py`, `app/web/materials.py` |
| Ngân hàng câu hỏi | Trắc nghiệm, trả lời ngắn, tự luận ngắn; lời giải từng bước; AI soạn câu nháp từ tài liệu đã duyệt, giáo viên duyệt | `app/web/bank.py` |
| Đánh giá đầu vào | Bài kiểm tra không có AI, tính giờ; khởi tạo mức nắm vững | `app/services/assessment.py` |
| Lộ trình cá nhân | Mức nắm vững theo chủ đề (Bayesian Knowledge Tracing có trọng số), chủ đề tiên quyết, đề xuất chủ đề tiếp theo, chọn câu theo độ khó, ôn lại giãn cách | `app/services/mastery.py`, `app/services/pathway.py` |
| Hỗ trợ thích ứng | Bậc thang gợi ý 5 mức, bắt buộc thử trước khi hỏi, giảm dần hỗ trợ, khóa lời giải, bộ lọc lộ đáp án | `app/services/tutor.py`, `app/ai/prompts.py` |
| Thực nghiệm | Chia nhóm cân bằng theo điểm đầu vào; so sánh điểm sau học, điểm ghi nhớ, tỉ lệ tự giải, mức hỗ trợ; kiểm định t (Welch), Cohen's d; biểu đồ theo tuần; xuất CSV ẩn danh | `app/services/experiment.py`, `app/services/stats.py` |
| Quản lý lớp | Nhập danh sách (dán hoặc Excel), phiếu đăng nhập có mã QR, hồ sơ học tập, xem toàn bộ hội thoại của từng phiên, xem như học sinh | `app/web/classes.py` |

Chi tiết thuật toán và thiết kế thực nghiệm: [docs/thiet-ke-he-thong.md](docs/thiet-ke-he-thong.md).

## Bậc thang gợi ý

| Mức | Tên | AI làm gì |
|---|---|---|
| 1 | Định hướng | Hỏi gợi mở: đề hỏi gì, em đã biết gì |
| 2 | Gợi nhắc kiến thức | Nhắc khái niệm trong tài liệu giáo viên đã duyệt |
| 3 | Gợi ý cách làm | Nêu hướng giải hoặc bước đầu tiên |
| 4 | Làm mẫu một phần | Các bước trung gian, để học sinh làm bước cuối |
| 5 | Lời giải chi tiết | Chỉ mở khi đã sai 2 lần và đã xem mức 4 |

Học sinh đã nắm vững chủ đề (từ 70%) chỉ được gợi ý tối đa mức 3 cho tới khi đã thử đủ số lần. Giáo viên chỉnh các ngưỡng này trong trang môn học.

## Chạy trên Windows

1. Cài Python 3.10 trở lên tại https://www.python.org/downloads/ (nhớ tích "Add python.exe to PATH").
2. Nhấp đúp `run.bat`. Lần đầu, script tạo môi trường ảo, cài thư viện, tạo tệp `.env` rồi mở trình duyệt.
3. Tạo tài khoản giáo viên đầu tiên, rồi bấm "Nạp dữ liệu mẫu Tin học 10 (Python)" ở trang Tổng quan để dùng thử ngay.

Dữ liệu mẫu gồm 5 chủ đề Python, tài liệu đã duyệt, 35 câu hỏi, 3 bài kiểm tra và lớp 12 học sinh với lịch sử luyện tập mô phỏng 3 tuần. Số liệu mẫu chỉ để xem giao diện, không phải kết quả thực nghiệm.

Chạy thủ công (Windows, macOS, Linux):

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
python -m app.cli seed-demo     # (tùy chọn) tài khoản demo@truonghoc.vn / demo1234 kèm dữ liệu mẫu
uvicorn app.main:create_app --factory --port 8000
```

## Học sinh vào học

- Giáo viên vào Lớp học → In phiếu đăng nhập. Mỗi phiếu có mã 6 ký tự và mã QR.
- Học sinh quét QR, hoặc mở `http://<địa chỉ máy chủ>:8000/hs` và nhập mã.
- Dùng trong phòng máy: đặt `PUBLIC_BASE_URL=http://<IP máy giáo viên>:8000` trong `.env` để mã QR trỏ đúng địa chỉ, và cho phép Python qua tường lửa Windows.

## Kết nối Gemini

Khi chưa có khóa, AI chạy chế độ demo: gợi ý dựng theo luật từ lời giải mẫu và tài liệu đã duyệt, vẫn đúng bậc thang nhưng chưa cá nhân hóa theo câu trả lời.

1. Lấy khóa tại https://aistudio.google.com/apikey.
2. Điền `GEMINI_API_KEY=...` vào `.env`, khởi động lại.
3. `GEMINI_MODEL=gemini-flash-latest` là bí danh luôn trỏ tới bản Flash mới nhất. Khi chạy thực nghiệm nên ghi tên mô hình cụ thể để kết quả nhất quán.

## Quy trình thực nghiệm gợi ý

1. Tạo môn học, chủ đề, duyệt tài liệu, soạn câu luyện tập (có lời giải từng bước) và câu kiểm tra.
2. Tạo bài đầu vào, mở cho học sinh làm.
3. Ở trang lớp, bấm "Chia ngẫu nhiên cân bằng" (hoặc so sánh theo lớp: mỗi lớp một chế độ mặc định).
4. Học sinh luyện tập 2–4 tuần.
5. Mở bài kiểm tra sau học, rồi 1–2 tuần sau mở bài ghi nhớ.
6. Xem báo cáo ở tab Thực nghiệm của môn học; xuất CSV để phân tích tiếp.

## Đưa lên web bằng Vercel

Dự án đã có sẵn `vercel.json` và `api/index.py`, Vercel chạy ứng dụng như một hàm Python. Vì máy chủ Vercel không giữ tệp, dữ liệu phải lưu ở PostgreSQL (Neon, gói miễn phí).

1. Đưa thư mục dự án lên một kho GitHub mới (GitHub Desktop: File → Add local repository → Publish). Tệp `.env` và thư mục `data/` không được đưa lên.
2. Vào https://vercel.com, đăng nhập bằng GitHub, chọn Add New → Project → Import kho vừa tạo. Framework Preset để Other, bấm Deploy.
3. Trong dự án Vercel: Storage → Create Database → Neon (Postgres) → Connect. Vercel tự thêm biến `DATABASE_URL` / `POSTGRES_URL`, web tự nhận.
4. Settings → Environment Variables, thêm:
   - `GEMINI_API_KEY`: khóa Gemini (bỏ trống thì AI chạy chế độ demo)
   - `SECRET_KEY`: một chuỗi ngẫu nhiên dài bất kỳ (khóa ký phiên đăng nhập)
   - `GEMINI_MODEL` (tùy chọn)
5. Deployments → Redeploy để áp dụng biến mới. Mở địa chỉ `https://<tên-dự-án>.vercel.app`, tạo tài khoản giáo viên đầu tiên.

Cách khác không cần GitHub: cài Node.js, mở cửa sổ lệnh trong thư mục dự án, chạy `npx vercel` rồi `npx vercel --prod`.

Lưu ý khi chạy trên Vercel:
- Mã QR trên phiếu đăng nhập tự lấy tên miền `.vercel.app`, không cần đặt `PUBLIC_BASE_URL`.
- Tệp tài liệu tải lên tối đa khoảng 4 MB (giới hạn của Vercel); tài liệu lớn hơn hãy dán nội dung.
- Mỗi yêu cầu tối đa 60 giây (`maxDuration` trong `vercel.json`), đủ cho một lần gọi Gemini.
- Nếu chưa nối PostgreSQL, trang giáo viên hiện cảnh báo đỏ vì dữ liệu sẽ mất khi máy chủ khởi động lại.

## Triển khai khác

- Docker: `cp .env.example .env` rồi `docker compose up -d --build`. Dữ liệu nằm ở thư mục `./data`.
- Render: tệp `render.yaml` có sẵn. Ổ đĩa của gói miễn phí bị xóa khi khởi động lại, nên khi dùng thật hãy tạo PostgreSQL và đặt `DATABASE_URL`.
- Chỉ chạy một tiến trình với SQLite. Khi nhiều lớp dùng cùng lúc nên chuyển sang PostgreSQL.

## Lệnh quản trị

```bash
python -m app.cli create-teacher --name "Nguyễn Văn A" --email a@truong.edu.vn --password matkhau
python -m app.cli reset-password --email a@truong.edu.vn --password matkhaumoi
python -m app.cli seed-demo
```

## Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest          # 24 bài kiểm thử: BKT, chấm đáp án, chặn lộ đáp án, kho tri thức, thống kê, hai chế độ AI, web
ruff check .
```

Bộ kiểm thử không cần Internet (AI chạy chế độ demo). Đã kiểm tra trên Python 3.10 và 3.13.

## Cấu trúc thư mục

```
app/
  main.py, config.py, db.py, models.py, security.py, seed.py, cli.py
  ai/          base (giao diện), gemini, mock (chế độ demo), prompts (lời nhắc), schemas
  services/    knowledge, mastery, pathway, tutor, assessment, experiment, stats, exporter, students, qr
  web/         các trang giáo viên, học sinh và API luyện tập
  templates/, static/
tests/
docs/thiet-ke-he-thong.md
```

## Dữ liệu và quyền riêng tư

- Mật khẩu băm scrypt, mọi form có mã CSRF, giáo viên chỉ thấy dữ liệu lớp của mình.
- Hệ thống không gửi họ tên học sinh cho AI. Tệp CSV xuất cho nghiên cứu dùng mã ẩn danh.
- Học sinh phần lớn chưa đủ 18 tuổi: cần thông báo và xin đồng ý của phụ huynh trước khi thu thập dữ liệu.
- Sao lưu thư mục `data/` định kỳ.
