"""Number formatting for templates (Indian digit grouping: 12,34,567.89)."""

from __future__ import annotations


def _group_indian(int_part: str) -> str:
    if len(int_part) <= 3:
        return int_part
    head, tail = int_part[:-3], int_part[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def num(value, decimals: int = 2, blank_zero: bool = False) -> str:
    if value is None or value == "":
        return ""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if blank_zero and abs(x) < 1e-12:
        return ""
    sign = "-" if x < 0 else ""
    text = f"{abs(x):.{decimals}f}"
    int_part, _, frac = text.partition(".")
    return sign + _group_indian(int_part) + ("." + frac if frac else "")


def inr(value, decimals: int = 2, blank_zero: bool = False) -> str:
    text = num(value, decimals, blank_zero)
    if not text:
        return ""
    return ("-₹" + text[1:]) if text.startswith("-") else "₹" + text


def pct(value, decimals: int = 0) -> str:
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return ""


def val(value, keep_zero: bool = False) -> str:
    """A number as it should appear inside an input box: 170.0 -> 170, 0 -> blank."""
    if value is None or value == "":
        return ""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if x == 0 and not keep_zero:
        return ""
    return str(int(x)) if x.is_integer() else f"{x:.10g}"
