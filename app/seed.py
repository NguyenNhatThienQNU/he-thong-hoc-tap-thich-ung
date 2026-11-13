"""Dữ liệu mẫu: môn Tin học 10 – Lập trình Python cơ bản, một lớp 12 học sinh và lịch sử luyện tập mô phỏng.

Lịch sử luyện tập được tạo bằng chính các hàm của hệ thống (gia sư AI chế độ demo), sau đó dời thời gian về
3–4 tuần trước để trang báo cáo có dữ liệu. Toàn bộ học sinh mẫu được đánh dấu is_demo; trang báo cáo
hiển thị cảnh báo đây là dữ liệu mô phỏng, KHÔNG phải kết quả thực nghiệm.
"""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai.mock import MockProvider
from .models import MODE_DIRECT, Classroom, Course, Exam, Material, PracticeSession, Question, Teacher, Topic
from .services import tutor
from .services.assessment import exam_questions, start_attempt, submit_attempt
from .services.experiment import balanced_assignment
from .services.knowledge import approve_material
from .services.mastery import get_mastery
from .services.students import add_student
from .utils.timeutil import utcnow

COURSE_NAME = "Tin học 10 – Lập trình Python cơ bản"

TOPICS = [
    {
        "name": "Biến, kiểu dữ liệu và phép toán",
        "prereq": [],
        "material": """Biến là tên dùng để lưu trữ một giá trị trong chương trình. Lệnh gán có dạng <tên biến> = <biểu thức>, ví dụ a = 5 gán giá trị 5 cho biến a. Tên biến chỉ gồm chữ cái, chữ số và dấu gạch dưới, không bắt đầu bằng chữ số và có phân biệt chữ hoa, chữ thường.

Các kiểu dữ liệu cơ bản: int là kiểu số nguyên (ví dụ 7), float là kiểu số thực (ví dụ 3.5), str là kiểu xâu kí tự đặt trong cặp dấu nháy (ví dụ "Python"), bool là kiểu logic chỉ có hai giá trị True và False. Hàm type(x) cho biết kiểu dữ liệu của x.

Các phép toán số học: + (cộng), - (trừ), * (nhân), / (chia, luôn cho kết quả là số thực), // (chia lấy phần nguyên), % (chia lấy phần dư), ** (lũy thừa). Ví dụ: 17 // 5 cho 3, 17 % 5 cho 2, 2 ** 3 cho 8, 7 / 2 cho 3.5.

Thứ tự thực hiện: lũy thừa được tính trước, sau đó đến nhân, chia, chia lấy phần nguyên, chia lấy phần dư, cuối cùng là cộng và trừ. Có thể dùng cặp ngoặc tròn để thay đổi thứ tự thực hiện.

Lệnh input() nhập dữ liệu từ bàn phím và luôn trả về một xâu kí tự. Muốn nhận số nguyên cần chuyển kiểu bằng int(input()), muốn nhận số thực dùng float(input()). Lệnh print() đưa dữ liệu ra màn hình; các giá trị viết cách nhau bởi dấu phẩy sẽ được in cách nhau một dấu cách.""",
        "practice": [
            ("Biểu thức `17 // 5` cho kết quả bằng bao nhiêu?", "3", "Phép // là phép chia lấy phần nguyên.\n17 chia 5 được thương là 3, dư 2.\nĐáp án: 3", 1),
            ("Biểu thức `2 + 3 * 2 ** 2` cho kết quả bằng bao nhiêu?", "14", "Thực hiện lũy thừa trước: 2 ** 2 = 4.\nTiếp theo là phép nhân: 3 * 4 = 12.\nCuối cùng là phép cộng 2 với kết quả vừa tính.\nĐáp án: 14", 2),
            ("Cho `a = 7` và `b = 2`. Biểu thức `a / b + a % b` cho kết quả bằng bao nhiêu?", "4.5\n4,5", "Phép / luôn cho số thực: 7 / 2 = 3.5.\nPhép % lấy phần dư: 7 % 2 = 1.\nCộng hai kết quả vừa tìm được.\nĐáp án: 4.5", 2),
            ("Viết lệnh nhập một số nguyên từ bàn phím và gán cho biến `n` (không cần câu nhắc).", "n = int(input())", "Lệnh input() luôn trả về xâu kí tự.\nCần chuyển xâu sang số nguyên bằng hàm int().\nGán kết quả cho biến n bằng lệnh gán.\nĐáp án: n = int(input())", 3),
        ],
        "test": [
            ("Kiểu dữ liệu của giá trị `3.5` trong Python là gì?", ["int", "float", "str", "bool"], 1, 1),
            ("Biểu thức `19 % 4` có giá trị bằng bao nhiêu?", ["4", "3", "4.75", "15"], 1, 2),
            ("Lệnh nào nhập một số thực từ bàn phím và gán cho biến `x`?", ["x = input()", "x = float(input())", "x = int(input())", "float x = input()"], 1, 2),
        ],
    },
    {
        "name": "Câu lệnh rẽ nhánh if",
        "prereq": [0],
        "material": """Câu lệnh rẽ nhánh cho phép chương trình chọn thực hiện các lệnh khác nhau tùy theo điều kiện. Điều kiện là một biểu thức logic, chỉ nhận một trong hai giá trị True (đúng) hoặc False (sai).

Các phép so sánh: == (bằng), != (khác), < (nhỏ hơn), > (lớn hơn), <= (nhỏ hơn hoặc bằng), >= (lớn hơn hoặc bằng). Lưu ý: dấu = là phép gán, còn == là phép so sánh bằng.

Các phép toán logic: and (và) cho kết quả đúng khi cả hai vế đều đúng; or (hoặc) cho kết quả đúng khi ít nhất một vế đúng; not (phủ định) đổi đúng thành sai và ngược lại.

Dạng thiếu: if <điều kiện>: rồi đến khối lệnh viết thụt lề ở các dòng dưới. Khối lệnh chỉ được thực hiện khi điều kiện đúng.

Dạng đủ: if <điều kiện>: <khối lệnh 1> else: <khối lệnh 2>. Nếu điều kiện đúng thì thực hiện khối lệnh 1, ngược lại thực hiện khối lệnh 2.

Nhiều nhánh: if ... elif ... else. Python kiểm tra lần lượt các điều kiện từ trên xuống, gặp điều kiện đúng đầu tiên thì thực hiện khối lệnh tương ứng và bỏ qua các nhánh còn lại. Các lệnh trong cùng một khối phải thụt lề như nhau, thường là 4 dấu cách.""",
        "practice": [
            ("Cho `n = 15`. Biểu thức `n % 2 == 0` nhận giá trị True hay False?", "False", "15 chia 2 dư 1 nên n % 2 có giá trị 1.\nSo sánh 1 == 0 là một so sánh sai.\nĐáp án: False", 1),
            ("Cho `x = 4`, `y = 7`. Biểu thức `(x > 5) or (y % 7 == 0)` nhận giá trị True hay False?", "True", "Vế trái: 4 > 5 là sai.\nVế phải: 7 % 7 = 0 nên y % 7 == 0 là đúng.\nPhép or đúng khi ít nhất một vế đúng.\nĐáp án: True", 2),
            ("Đoạn chương trình sau in ra gì?\n```\na = 10\nif a > 5:\n    a = a - 3\nelse:\n    a = a + 3\nprint(a)\n```", "7", "Điều kiện a > 5 (10 > 5) là đúng nên thực hiện nhánh if.\nLệnh a = a - 3 làm a giảm đi 3.\nĐáp án: 7", 2),
            ("Đoạn chương trình sau in ra gì khi `n = 75`?\n```\nif n >= 80:\n    print('Giỏi')\nelif n >= 65:\n    print('Khá')\nelif n >= 50:\n    print('Trung bình')\nelse:\n    print('Yếu')\n```", "Khá", "Kiểm tra lần lượt từ trên xuống: 75 >= 80 là sai.\nĐiều kiện tiếp theo 75 >= 65 là đúng nên thực hiện nhánh này và bỏ qua các nhánh sau.\nĐáp án: Khá", 3),
        ],
        "test": [
            ("Trong Python, phép so sánh “khác” được viết như thế nào?", ["<>", "!=", "=/=", "not ="], 1, 1),
            ("Với `a = 3`, `b = 8`, biểu thức nào có giá trị True?", ["a > b and b > 5", "a == b or a > 5", "not (a < b)", "a < b and b < 10"], 3, 2),
            ("Đoạn lệnh sau in ra gì?\n```\nx = 12\nif x % 3 == 0:\n    print('A')\nelif x % 2 == 0:\n    print('B')\nelse:\n    print('C')\n```", ["A", "B", "A và B", "C"], 0, 3),
        ],
    },
    {
        "name": "Vòng lặp for và hàm range()",
        "prereq": [0],
        "material": """Vòng lặp for dùng để lặp lại một khối lệnh với số lần biết trước. Cú pháp: for <biến> in range(...): rồi đến khối lệnh viết thụt lề.

Hàm range(n) tạo dãy số nguyên từ 0 đến n - 1, gồm n số. Ví dụ range(5) gồm các số 0, 1, 2, 3, 4.

Hàm range(a, b) tạo dãy số nguyên từ a đến b - 1, không gồm b. Ví dụ range(2, 6) gồm các số 2, 3, 4, 5.

Hàm range(a, b, k) tạo dãy bắt đầu từ a, mỗi lần tăng thêm k và dừng trước khi đạt tới b. Ví dụ range(1, 10, 3) gồm 1, 4, 7. Nếu k là số âm thì dãy giảm dần, ví dụ range(5, 0, -1) gồm 5, 4, 3, 2, 1.

Mẫu tính tổng: khởi tạo s = 0, trong vòng lặp thực hiện s = s + i. Ví dụ tính tổng 1 + 2 + ... + n: viết s = 0 rồi for i in range(1, n + 1): s = s + i.

Mẫu đếm: khởi tạo dem = 0, mỗi khi gặp giá trị thỏa mãn điều kiện thì tăng dem thêm 1 bằng lệnh dem = dem + 1.""",
        "practice": [
            ("Dãy `range(2, 7)` gồm bao nhiêu số?", "5", "range(a, b) gồm các số nguyên từ a đến b - 1.\nCác số của range(2, 7) là 2, 3, 4, 5, 6.\nĐáp án: 5", 1),
            ("Đoạn chương trình sau in ra gì?\n```\ns = 0\nfor i in range(1, 5):\n    s = s + i\nprint(s)\n```", "10", "range(1, 5) gồm các số 1, 2, 3, 4.\nSau mỗi lần lặp, s lần lượt bằng 1, 3, 6 rồi cộng thêm 4.\nĐáp án: 10", 2),
            ("Đoạn chương trình sau in ra gì?\n```\ndem = 0\nfor i in range(1, 21):\n    if i % 3 == 0:\n        dem = dem + 1\nprint(dem)\n```", "6", "i chạy từ 1 đến 20.\nCần đếm các số chia hết cho 3 trong khoảng này: 3, 6, 9, 12, 15, 18.\nĐáp án: 6", 3),
            ("Viết dòng tiêu đề của vòng lặp for để biến `i` lần lượt nhận các giá trị 10, 8, 6, 4, 2.", "for i in range(10, 0, -2):\nfor i in range(10, 1, -2):\nfor i in range(10, 0, -2)\nfor i in range(10, 1, -2)", "Dãy giảm dần từ 10, mỗi bước giảm 2 nên dùng range(a, b, k) với k = -2.\nSố bắt đầu a = 10; dãy phải dừng trước 0 nên chọn b = 0 (hoặc 1).\nĐáp án: for i in range(10, 0, -2):", 3),
        ],
        "test": [
            ("`range(5)` tạo ra dãy số nào?", ["1, 2, 3, 4, 5", "0, 1, 2, 3, 4", "0, 1, 2, 3, 4, 5", "5"], 1, 1),
            ("Đoạn lệnh sau in ra bao nhiêu dòng?\n```\nfor i in range(3, 12, 3):\n    print(i)\n```", ["3", "4", "9", "12"], 0, 2),
            ("Để tính tổng S = 1 + 2 + ... + n (ban đầu S = 0, trong thân vòng lặp có S = S + i), dòng lệnh for nào đúng?", ["for i in range(n):", "for i in range(1, n):", "for i in range(1, n + 1):", "for i in range(0, n - 1):"], 2, 3),
        ],
    },
    {
        "name": "Vòng lặp while",
        "prereq": [1, 2],
        "material": """Vòng lặp while dùng để lặp với số lần chưa biết trước: khối lệnh được thực hiện chừng nào điều kiện còn đúng. Cú pháp: while <điều kiện>: rồi đến khối lệnh viết thụt lề.

Python kiểm tra điều kiện trước mỗi lần lặp. Nếu ngay từ đầu điều kiện đã sai thì khối lệnh không được thực hiện lần nào.

Trong khối lệnh cần có lệnh làm thay đổi giá trị liên quan đến điều kiện; nếu không, điều kiện luôn đúng và vòng lặp chạy mãi (lặp vô hạn).

Lệnh break dùng để thoát ngay khỏi vòng lặp. Lệnh continue bỏ qua phần còn lại của lần lặp hiện tại và chuyển sang lần lặp tiếp theo.

Ví dụ đếm số chữ số của số nguyên dương n: khởi tạo dem = 0; trong khi n > 0 thì thực hiện n = n // 10 và dem = dem + 1. Mỗi lần chia nguyên cho 10, số n mất đi chữ số cuối cùng.""",
        "practice": [
            ("Đoạn chương trình sau in ra gì?\n```\ni = 1\nwhile i < 10:\n    i = i * 2\nprint(i)\n```", "16", "i lần lượt nhận các giá trị 1, 2, 4, 8.\nKhi i = 8 điều kiện 8 < 10 vẫn đúng nên i được nhân đôi thêm một lần, sau đó điều kiện sai và vòng lặp dừng.\nĐáp án: 16", 1),
            ("Vòng lặp sau thực hiện bao nhiêu lần?\n```\nn = 20\nwhile n > 0:\n    n = n - 6\n```", "4", "Theo dõi giá trị n sau mỗi lần lặp: 20 → 14 → 8 → 2 → -4.\nKhi n = -4 điều kiện n > 0 sai nên vòng lặp dừng; đếm số mũi tên chính là số lần lặp.\nĐáp án: 4", 2),
            ("Đoạn chương trình sau in ra gì?\n```\nn = 2024\ndem = 0\nwhile n > 0:\n    n = n // 10\n    dem = dem + 1\nprint(dem)\n```", "4", "Mỗi lần lặp, n // 10 bỏ đi chữ số cuối cùng của n và dem tăng 1.\nn lần lượt là 2024 → 202 → 20 → 2 → 0, nên dem bằng số chữ số của 2024.\nĐáp án: 4", 3),
            ("Đoạn chương trình sau in ra gì?\n```\ns = 0\ni = 0\nwhile True:\n    i = i + 1\n    if i % 2 == 0:\n        continue\n    s = s + i\n    if i >= 7:\n        break\nprint(s)\n```", "16", "Lệnh continue bỏ qua các giá trị i chẵn, nên s chỉ cộng các giá trị i lẻ.\nKhi i = 7 thì sau khi cộng vào s, điều kiện i >= 7 đúng nên break thoát vòng lặp: s = 1 + 3 + 5 + 7.\nĐáp án: 16", 4),
        ],
        "test": [
            ("Vòng lặp while thường được dùng khi nào?", ["Khi biết trước số lần lặp", "Khi chưa biết trước số lần lặp, lặp chừng nào điều kiện còn đúng", "Khi chỉ cần thực hiện lệnh đúng một lần", "Khi cần rẽ nhánh theo điều kiện"], 1, 1),
            ("Lệnh nào dùng để thoát ngay khỏi vòng lặp?", ["continue", "exit loop", "break", "stop"], 2, 2),
            ("Đoạn lệnh sau in ra gì?\n```\nk = 0\nwhile k < 5:\n    k = k + 2\nprint(k)\n```", ["4", "5", "6", "8"], 2, 2),
        ],
    },
    {
        "name": "Kiểu danh sách (list)",
        "prereq": [2],
        "material": """Danh sách (list) là kiểu dữ liệu lưu nhiều giá trị theo thứ tự, viết trong cặp ngoặc vuông, các phần tử cách nhau bởi dấu phẩy. Ví dụ a = [3, 8, 5].

Các phần tử được đánh chỉ số bắt đầu từ 0: a[0] là phần tử đầu tiên; a[len(a) - 1] hoặc a[-1] là phần tử cuối cùng. Hàm len(a) cho biết số phần tử của danh sách.

Có thể thay đổi giá trị một phần tử bằng lệnh gán, ví dụ a[1] = 10.

Phương thức a.append(x) thêm x vào cuối danh sách; a.insert(i, x) chèn x vào vị trí có chỉ số i; a.remove(x) xóa phần tử có giá trị x đầu tiên tìm thấy; a.pop() xóa và trả về phần tử cuối cùng; a.clear() xóa toàn bộ danh sách.

Toán tử in kiểm tra một giá trị có thuộc danh sách hay không, ví dụ với a = [3, 8, 5] thì 5 in a cho kết quả True.

Duyệt danh sách: dùng for x in a: để lấy lần lượt từng phần tử, hoặc for i in range(len(a)): và truy cập a[i]. Các hàm sum(a), max(a), min(a) lần lượt cho tổng, giá trị lớn nhất và giá trị nhỏ nhất của danh sách số.""",
        "practice": [
            ("Cho `a = [4, 9, 2, 7]`. Giá trị của `a[2]` là bao nhiêu?", "2", "Chỉ số của danh sách bắt đầu từ 0.\na[0] = 4, a[1] = 9, phần tử tiếp theo có chỉ số 2.\nĐáp án: 2", 1),
            ("Cho `a = [5, 3, 8]`. Sau lệnh `a.append(6)`, giá trị của `len(a)` là bao nhiêu?", "4", "Ban đầu danh sách có 3 phần tử.\nappend thêm đúng một phần tử vào cuối danh sách.\nĐáp án: 4", 2),
            ("Cho `a = [1, 4, 6, 3]`. Biểu thức `a[-1] + a[1]` có giá trị bằng bao nhiêu?", "7", "a[-1] là phần tử cuối cùng: 3.\na[1] là phần tử thứ hai (chỉ số 1): 4.\nĐáp án: 7", 2),
            ("Đoạn chương trình sau in ra gì?\n```\na = [3, 10, 4, 7, 12]\ndem = 0\nfor x in a:\n    if x % 2 == 0:\n        dem = dem + 1\nprint(dem)\n```", "3", "Vòng lặp duyệt lần lượt từng phần tử x của danh sách.\nĐếm các phần tử chẵn: 10, 4 và 12.\nĐáp án: 3", 3),
        ],
        "test": [
            ("Phần tử đầu tiên của danh sách `a` có chỉ số là bao nhiêu?", ["1", "0", "-1", "len(a)"], 1, 1),
            ("Cho `a = [2, 5, 8]`. Sau lệnh `a.insert(1, 9)`, danh sách `a` là:", ["[9, 2, 5, 8]", "[2, 9, 5, 8]", "[2, 5, 9, 8]", "[2, 5, 8, 9]"], 1, 2),
            ("Cho `a = [6, 1, 9, 4]`. Lệnh `print(max(a) - min(a))` in ra:", ["8", "5", "3", "10"], 0, 2),
        ],
    },
]

STUDENTS = [
    "Nguyễn Minh Anh", "Trần Gia Bảo", "Lê Ngọc Châu", "Phạm Đức Duy", "Hoàng Thu Hà", "Võ Quang Huy",
    "Đặng Bảo Khánh", "Bùi Thảo Linh", "Đỗ Hoàng Nam", "Ngô Phương Nhi", "Huỳnh Tấn Phát", "Phan Minh Thư",
]

THINKING = [
    "Em chưa biết bắt đầu từ đâu ạ, em đọc đề mà chưa hiểu cần làm gì.",
    "Em nghĩ phải tính từng bước nhưng em không chắc thứ tự thực hiện.",
    "Em đã thử tính nhưng ra kết quả khác, em không biết sai ở đâu.",
    "Em quên cú pháp của lệnh này rồi ạ, nó hoạt động thế nào?",
    "Em làm theo gợi ý rồi nhưng vẫn còn vướng ở bước tiếp theo.",
]


def build_course(db: Session, teacher: Teacher, name: str = COURSE_NAME) -> tuple[Course, list[Topic]]:
    existing = {c.name for c in db.scalars(select(Course).where(Course.teacher_id == teacher.id)).all()}
    final_name, i = name, 2
    while final_name in existing:
        final_name, i = f"{name} ({i})", i + 1
    course = Course(
        teacher_id=teacher.id,
        name=final_name,
        grade="10",
        description="Dữ liệu mẫu: 5 chủ đề lập trình Python cơ bản, tài liệu đã duyệt, câu luyện tập và bài kiểm tra.",
        policy={},
    )
    db.add(course)
    db.flush()
    topics: list[Topic] = []
    for pos, spec in enumerate(TOPICS, 1):
        topic = Topic(course_id=course.id, name=spec["name"], position=pos, prerequisite_ids=[])
        db.add(topic)
        db.flush()
        topics.append(topic)
    for topic, spec in zip(topics, TOPICS, strict=True):
        topic.prerequisite_ids = [topics[i].id for i in spec["prereq"]]
        material = Material(
            course_id=course.id,
            topic_id=topic.id,
            title=f"Bài học: {spec['name']}",
            content=spec["material"],
            filename="",
            status="pending",
        )
        db.add(material)
        db.flush()
        approve_material(db, material, True)
        for stem, answer, solution, level in spec["practice"]:
            db.add(
                Question(
                    course_id=course.id, topic_id=topic.id, kind="short", stem=stem, answer=answer, solution=solution,
                    difficulty=level, purpose="practice", status="approved", source="demo",
                )
            )
        for stem, options, correct, level in spec["test"]:
            # Đảo vị trí phương án (cố định theo đề) để đáp án đúng không luôn nằm ở cùng một chữ cái
            order = list(range(len(options)))
            random.Random(stem).shuffle(order)
            options, correct = [options[i] for i in order], order.index(correct)
            db.add(
                Question(
                    course_id=course.id, topic_id=topic.id, kind="mcq", stem=stem, options=options,
                    correct_option=correct, solution=f"Đáp án: {options[correct]}", difficulty=level, purpose="test",
                    status="approved", source="demo",
                )
            )
    db.flush()
    return course, topics


def _test_ids(course: Course, topics: list[Topic], index_set: tuple[int, ...]) -> list[int]:
    ids = []
    for t in topics:
        tests = [q for q in course.questions if q.topic_id == t.id and q.purpose == "test"]
        tests.sort(key=lambda q: q.id)
        ids.extend(tests[i].id for i in index_set if i < len(tests))
    return ids


def _simulate_exam(db, ai, exam, student, p_correct: float, rng: random.Random, when) -> None:
    attempt = start_attempt(db, exam, student)
    answers = {}
    for q in exam_questions(db, exam):
        if rng.random() < p_correct:
            answers[str(q.id)] = str(q.correct_option)
        else:
            wrong = [i for i in range(len(q.options_list)) if i != q.correct_option]
            answers[str(q.id)] = str(rng.choice(wrong))
    submit_attempt(db, ai, exam, attempt, answers, use_ai=False)
    attempt.started_at = when
    attempt.submitted_at = when + timedelta(minutes=rng.randint(8, 14))


def _wrong_answer(question: Question, rng: random.Random) -> str:
    first = question.accepted_answers[0] if question.accepted_answers else ""
    num = tutor.to_number(first)
    if num is not None:
        return str(int(num) + rng.choice([-2, -1, 1, 2])) if float(num).is_integer() else str(num + 1)
    if first in ("True", "False"):
        return "True" if first == "False" else "False"
    return rng.choice(["Giỏi", "Trung bình", "for i in range(10, 2):", "n = input()"])


def _simulate_session(db, ai, student, question, mode, week, ability, rng, start) -> None:
    m = get_mastery(db, student.id, question.topic_id)
    s = PracticeSession(
        student_id=student.id, question_id=question.id, topic_id=question.topic_id, mode=mode, status="active",
        started_at=start, p_before=m.p_known, wrong_options=[],
    )
    db.add(s)
    db.flush()
    correct = question.accepted_answers[0]
    if mode == MODE_DIRECT:
        # Nhóm đối chứng: phần lớn hỏi AI lời giải ngay, tỉ lệ không giảm theo thời gian
        if rng.random() < 0.62 - 0.25 * ability + 0.04 * week:
            tutor.view_solution(db, ai, s)
        elif rng.random() > ability:
            tutor.submit_answer(db, ai, s, _wrong_answer(question, rng))
            if rng.random() < 0.7:
                tutor.view_solution(db, ai, s)
        tutor.submit_answer(db, ai, s, correct)
    else:
        # Nhóm thực nghiệm: số gợi ý cần dùng giảm dần theo tuần khi các em quen tự làm
        need = max(0, round(rng.gauss(2.6 - 0.75 * week - 1.6 * (ability - 0.5), 0.8)))
        if need == 0:
            if rng.random() > ability + 0.15:
                tutor.submit_answer(db, ai, s, _wrong_answer(question, rng))
            tutor.submit_answer(db, ai, s, correct)
        else:
            for k in range(min(need, 4)):
                tutor.request_hint(db, ai, s, rng.choice(THINKING))
                if k < need - 1 and rng.random() < 0.5:
                    tutor.submit_answer(db, ai, s, _wrong_answer(question, rng))
            if need >= 5 and tutor.can_view_solution(s, question.course.full_policy)[0]:
                tutor.view_solution(db, ai, s)
            tutor.submit_answer(db, ai, s, correct)
    # Dời mốc thời gian về quá khứ
    t = start
    for msg in s.messages:
        t += timedelta(seconds=rng.randint(20, 90))
        msg.created_at = t
    s.ended_at = t + timedelta(seconds=rng.randint(5, 30))


def seed_demo_data(db: Session, teacher: Teacher, seed: int = 2026) -> tuple[Course, Classroom]:
    rng = random.Random(seed)
    ai = MockProvider()
    course, topics = build_course(db, teacher)
    now = utcnow().replace(hour=2, minute=0, second=0, microsecond=0)  # 9h sáng giờ Việt Nam
    pre = Exam(course_id=course.id, title="Bài kiểm tra đầu vào", kind="pre", duration_min=15,
               question_ids=_test_ids(course, topics, (0,)), is_open=False)
    post = Exam(course_id=course.id, title="Bài kiểm tra sau 3 tuần học", kind="post", duration_min=20,
                question_ids=_test_ids(course, topics, (1, 2)), is_open=False)
    retention_ids = _test_ids(course, topics, (1, 2))
    rng.shuffle(retention_ids)
    retention = Exam(course_id=course.id, title="Bài kiểm tra ghi nhớ (sau 9 ngày)", kind="retention",
                     duration_min=20, question_ids=retention_ids, is_open=False)
    db.add_all([pre, post, retention])
    classroom = Classroom(teacher_id=teacher.id, course_id=course.id, name="10A1 (dữ liệu mẫu)")
    db.add(classroom)
    db.flush()
    students = [add_student(db, classroom, name, f"HS{i:02d}", is_demo=True) for i, name in enumerate(STUDENTS, 1)]
    abilities = {st.id: rng.uniform(0.3, 0.85) for st in students}

    # 1) Bài đầu vào
    for st in students:
        _simulate_exam(db, ai, pre, st, 0.2 + 0.6 * abilities[st.id] * 0.8, rng, now - timedelta(days=30, hours=-1))
    db.flush()
    # 2) Chia nhóm cân bằng theo điểm đầu vào
    balanced_assignment(db, classroom, seed=seed)
    db.flush()
    # 3) Ba tuần luyện tập
    practice = {t.id: [q for q in course.questions if q.topic_id == t.id and q.purpose == "practice"] for t in topics}
    for st in students:
        ability = abilities[st.id]
        n_sessions = rng.randint(12, 16)
        for k in range(n_sessions):
            week = min(2, k * 3 // n_sessions)
            topic = topics[min(len(topics) - 1, k * len(topics) // n_sessions)]
            question = rng.choice(practice[topic.id])
            start = now - timedelta(days=28 - week * 6 - rng.randint(0, 5), hours=rng.randint(0, 8))
            _simulate_session(db, ai, st, question, st.effective_mode, week, ability, rng, start)
    db.flush()
    # 4) Bài ngay sau học và bài ghi nhớ (không có AI)
    for st in students:
        a = abilities[st.id]
        adaptive = st.effective_mode != MODE_DIRECT
        p_post = min(0.95, 0.35 + 0.55 * a + (0.06 if adaptive else 0.04))
        p_ret = max(0.1, p_post - (0.04 if adaptive else 0.12))
        _simulate_exam(db, ai, post, st, p_post, rng, now - timedelta(days=10))
        _simulate_exam(db, ai, retention, st, p_ret, rng, now - timedelta(days=1))
    db.flush()
    return course, classroom
