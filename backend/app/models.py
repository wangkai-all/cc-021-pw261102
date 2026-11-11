"""映射配置模型与单元格值解析（月份、金额、缺失、跳过行判定）。"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from .ranges import DimColumn

# 缺失标记：空白与 “—” 系列
MISSING_MARKERS = {"", "—", "–", "－", "-", "— ", " ", "／", "/", "N/A", "NA", "无"}

# 合计/小计/备注行关键字（行首维度文本命中即跳过展开，但保留用于核对）
SKIP_KEYWORDS = ("合计", "小计", "总计", "备注", "注：", "注:", "说明")

# 单位 -> 换算到“元”的乘数
UNIT_FACTORS: dict[str, float] = {
    "元": 1.0,
    "万元": 10_000.0,
}

MonthParseStatus = Literal["ok", "uncertain", "missing"]


@dataclass
class HeaderSelection:
    """表头区域选择（矩形，含多层表头）。"""
    row_start: int
    row_end: int
    col_start: int
    col_end: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.row_start, self.row_end, self.col_start, self.col_end


@dataclass
class DataSelection:
    """数据区域（矩形）。"""
    row_start: int
    row_end: int
    col_start: int
    col_end: int


@dataclass
class MappingConfig:
    """一份可复用的展开映射。"""
    name: str
    sheet_name: str
    report_year: int
    unit: str                         # 元 / 万元
    header: HeaderSelection
    data: DataSelection
    # 维度列：[{col, row_start, row_end, name}]
    dimensions: list[dict[str, Any]]
    # 渠道层表头值 -> 标准渠道名（线上/线下），未配置的按原值
    channel_aliases: dict[str, str] = field(default_factory=dict)
    # 结构指纹：表头区域填充后的二维文本，复用时比对
    fingerprint: str = ""

    def dim_columns(self) -> list[DimColumn]:
        return [
            DimColumn(
                col=int(d["col"]),
                row_start=int(d["row_start"]),
                row_end=int(d["row_end"]),
                name=str(d.get("name") or ""),
            )
            for d in self.dimensions
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------- Pydantic API 模型 ----------------

class DimColumnIn(BaseModel):
    col: int
    row_start: int
    row_end: int
    name: str = ""


class HeaderIn(BaseModel):
    row_start: int
    row_end: int
    col_start: int
    col_end: int


class DataIn(BaseModel):
    row_start: int
    row_end: int
    col_start: int
    col_end: int


class MappingPayload(BaseModel):
    name: str
    sheet_name: str
    report_year: int
    unit: str
    header: HeaderIn
    data: DataIn
    dimensions: list[DimColumnIn]
    channel_aliases: dict[str, str] = {}


# ---------------- 值解析 ----------------

_CN_MONTH_RE = re.compile(r"(\d{1,2})\s*月")
_DATE_RE = re.compile(r"(?:20)?\d{2}\s*[年/\-.]\s*(\d{1,2})\s*月?")
_BARE_NUM_RE = re.compile(r"^(\d{1,2})$")


def normalize_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def parse_month(v: Any, report_year: int) -> tuple[MonthParseStatus, str | None, str | None]:
    """把表头值解析为 ISO 月份 (YYYY-MM)。

    返回 (status, iso_month | None, display)
    - ok: 明确解析
    - missing: 空
    - uncertain: 有内容但拿不准（交给人工处理）
    """
    text = normalize_text(v)
    if text == "":
        return "missing", None, text
    m = _CN_MONTH_RE.search(text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return "ok", f"{report_year:04d}-{month:02d}", text
        return "uncertain", None, text
    m = _DATE_RE.search(text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return "ok", f"{report_year:04d}-{month:02d}", text
        return "uncertain", None, text
    m = _BARE_NUM_RE.match(text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return "ok", f"{report_year:04d}-{month:02d}", text
    return "uncertain", None, text


_NUM_CLEAN_RE = re.compile(r"[,\s，]")


def is_missing_value(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() in MISSING_MARKERS:
        return True
    return False


def parse_amount(v: Any, unit: str) -> tuple[float | None, str]:
    """金额解析并按单位换算为元。

    返回 (amount_in_yuan | None, status)
    status: ok / missing / unparseable
    字符串公式（data_only 视图下仍是 '=' 开头）不会进入这里——上层已按公式处理；
    任何无法解析为数字的文本返回 unparseable，绝不强转。
    """
    if is_missing_value(v):
        return None, "missing"
    if isinstance(v, bool):
        return None, "unparseable"
    if isinstance(v, (int, float)):
        factor = UNIT_FACTORS.get(unit)
        if factor is None:
            return None, "unparseable"
        return float(v) * factor, "ok"
    if isinstance(v, str):
        text = _NUM_CLEAN_RE.sub("", v.strip())
        # 公式文本绝不作为金额
        if text.startswith("="):
            return None, "formula_without_cache"
        try:
            num = float(text)
        except ValueError:
            return None, "unparseable"
        factor = UNIT_FACTORS.get(unit)
        if factor is None:
            return None, "unparseable"
        return num * factor, "ok"
    return None, "unparseable"


def row_skip_reason(first_dim_text: Any) -> str | None:
    """返回跳过原因；None 表示正常明细行。"""
    text = normalize_text(first_dim_text)
    if text == "":
        return None
    for kw in SKIP_KEYWORDS:
        if kw in text:
            if "备注" in text or text.startswith("注") or "说明" in text:
                return "note"
            return "total"
    return None
