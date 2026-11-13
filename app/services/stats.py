"""Thống kê cho báo cáo thực nghiệm: trung bình, độ lệch chuẩn, kiểm định t Welch, hệ số Cohen's d.

Viết thuần Python (không cần SciPy). Giá trị p hai phía của phân phối t được tính qua
hàm beta không đầy đủ chuẩn hóa (thuật toán phân số liên tục).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def sd(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _betacf(a: float, b: float, x: float) -> float:
    max_iter, eps, fpmin = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > fpmin else fpmin)
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > fpmin else fpmin)
        c = 1 + aa / c
        c = c if abs(c) > fpmin else fpmin
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > fpmin else fpmin)
        c = 1 + aa / c
        c = c if abs(c) > fpmin else fpmin
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Hàm beta không đầy đủ chuẩn hóa I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_bt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    bt = math.exp(ln_bt)
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def t_pvalue(t: float, df: float) -> float:
    """Giá trị p hai phía của thống kê t với df bậc tự do."""
    if df <= 0 or math.isnan(t):
        return float("nan")
    return betai(df / 2, 0.5, df / (df + t * t))


@dataclass
class Comparison:
    n_a: int
    n_b: int
    mean_a: float | None
    mean_b: float | None
    sd_a: float | None
    sd_b: float | None
    t: float | None = None
    df: float | None = None
    p: float | None = None
    d: float | None = None

    @property
    def diff(self) -> float | None:
        if self.mean_a is None or self.mean_b is None:
            return None
        return self.mean_a - self.mean_b

    @property
    def significant(self) -> bool:
        return self.p is not None and self.p < 0.05

    @property
    def effect_label(self) -> str:
        if self.d is None:
            return ""
        size = abs(self.d)
        if size < 0.2:
            return "rất nhỏ"
        if size < 0.5:
            return "nhỏ"
        if size < 0.8:
            return "trung bình"
        return "lớn"


def compare(a: list[float], b: list[float]) -> Comparison:
    """So sánh nhóm a (thực nghiệm) với nhóm b (đối chứng): kiểm định t Welch + Cohen's d."""
    result = Comparison(len(a), len(b), mean(a), mean(b), sd(a), sd(b))
    if len(a) < 2 or len(b) < 2:
        return result
    va, vb = result.sd_a**2, result.sd_b**2
    se2 = va / len(a) + vb / len(b)
    pooled = math.sqrt(((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2))
    if pooled > 0:
        result.d = (result.mean_a - result.mean_b) / pooled
    if se2 > 0:
        result.t = (result.mean_a - result.mean_b) / math.sqrt(se2)
        result.df = se2**2 / ((va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1))
        result.p = t_pvalue(result.t, result.df)
    return result
