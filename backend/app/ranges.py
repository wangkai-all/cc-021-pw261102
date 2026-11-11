"""区域解析与受限的合并单元格填充。

填充规则（严格按需求）：
- 只对“选定的表头区域”和“选定的维度列”补齐合并值；
- 表头内合并：沿合并区域把左上角值复制到覆盖的每个单元格（横向月份合并最常见）；
- 维度列内合并：仅当整个合并区域落在该维度列的选定行范围内时向下填充。
数据区域不做任何填充，空白保持空白（缺失）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.utils import column_index_from_string, get_column_letter

from .grid import SheetGrid

_A1_RE = re.compile(r"^([A-Za-z]{1,3})(\d+)$")
_RANGE_RE = re.compile(
    r"^\s*([A-Za-z]{1,3})(\d+)\s*:\s*([A-Za-z]{1,3})(\d+)\s*$"
)


@dataclass(frozen=True)
class DimColumn:
    """一个维度列：列号 + 该列参与处理的行范围（1 基，闭区间）。"""
    col: int
    row_start: int
    row_end: int
    name: str = ""          # 维度名，如 区域 / 门店


def parse_a1(coord: str) -> tuple[int, int]:
    m = _A1_RE.match(coord.strip())
    if not m:
        raise ValueError(f"非法单元格坐标: {coord!r}")
    return int(m.group(2)), column_index_from_string(m.group(1).upper())


def parse_range(text: str) -> tuple[int, int, int, int]:
    """返回 (min_row, max_row, min_col, max_col)，均为 1 基。"""
    m = _RANGE_RE.match(text)
    if not m:
        raise ValueError(f"非法区域（应为 A1:B2 形式）: {text!r}")
    r1, c1 = int(m.group(2)), column_index_from_string(m.group(1).upper())
    r2, c2 = int(m.group(4)), column_index_from_string(m.group(3).upper())
    return min(r1, r2), max(r1, r2), min(c1, c2), max(c1, c2)


def to_a1(row: int, col: int) -> str:
    return f"{get_column_letter(col)}{row}"


def fill_merges_in_scope(
    grid: SheetGrid,
    header_scope: tuple[int, int, int, int] | None,
    dims: list[DimColumn],
) -> dict[tuple[int, int], object]:
    """生成填充后的虚拟值表，只覆盖表头区域与维度列。

    返回 {(row, col): value}，包含这些范围内的逻辑值（原值 + 合并补值），
    不修改 grid 本身。数据区域不在返回范围内，绝不填充。
    """
    filled: dict[tuple[int, int], object] = {}

    def in_header_scope(r: int, c: int) -> bool:
        if header_scope is None:
            return False
        r1, r2, c1, c2 = header_scope
        return r1 <= r <= r2 and c1 <= c <= c2

    def in_dim_scope(r: int, c: int) -> DimColumn | None:
        for d in dims:
            if d.col == c and d.row_start <= r <= d.row_end:
                return d
        return None

    # 1) 原始值先落位（仅限定范围内）
    for (r, c), info in grid.cells.items():
        if in_header_scope(r, c) or in_dim_scope(r, c):
            if info.value is not None:
                filled[(r, c)] = info.value

    # 2) 合并区域补齐
    for mrg in grid.merges:
        key = (mrg.min_row, mrg.max_row, mrg.min_col, mrg.max_col)
        anchor_value = grid.merge_topleft.get(key)
        if anchor_value is None:
            continue
        for r in range(mrg.min_row, mrg.max_row + 1):
            for c in range(mrg.min_col, mrg.max_col + 1):
                if in_header_scope(r, c):
                    # 表头合并：落在表头范围内的部分补齐
                    filled.setdefault((r, c), anchor_value)
                else:
                    # 维度列合并：必须是单列纵向合并，且整段落在该维度列范围内
                    d = in_dim_scope(mrg.min_row, c)
                    if (
                        d is not None
                        and mrg.min_col == mrg.max_col == c
                        and in_dim_scope(mrg.max_row, c) is d
                    ):
                        filled.setdefault((r, c), anchor_value)
    return filled
