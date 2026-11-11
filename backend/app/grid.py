"""网格读取层：用 openpyxl 打开工作簿，保留公式与缓存两份视图。

设计要点：
- 同一工作簿打开两次：data_only=False 看公式文本，data_only=True 看缓存值。
- 单元格以 1 基坐标 (row, col) 暴露，坐标可直接反查 openpyxl 的 A1 表示。
- 合并单元格信息原样暴露，填充策略由上层决定（只在选定范围内补齐）。
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
import openpyxl


@dataclasses.dataclass
class CellInfo:
    row: int          # 1 基
    col: int          # 1 基
    value: Any        # data_only 视图下的值（公式缓存或字面值）
    raw: Any          # 公式视图下的原始内容（公式串或字面值）
    is_formula: bool
    has_cached_value: bool

    @property
    def coordinate(self) -> str:
        return f"{get_column_letter(self.col)}{self.row}"


@dataclasses.dataclass
class MergeRange:
    min_row: int
    max_row: int
    min_col: int
    max_col: int

    def contains(self, row: int, col: int) -> bool:
        return self.min_row <= row <= self.max_row and self.min_col <= col <= self.max_col


@dataclasses.dataclass
class SheetGrid:
    name: str
    max_row: int
    max_col: int
    # cells[(row, col)] -> CellInfo；稀疏存储
    cells: dict[tuple[int, int], CellInfo]
    merges: list[MergeRange]
    # 每个合并区域左上角的值（填充时使用）
    merge_topleft: dict[tuple[int, int, int, int], Any]

    def get(self, row: int, col: int) -> CellInfo | None:
        return self.cells.get((row, col))

    def display_value(self, row: int, col: int) -> Any:
        """展示用值：优先缓存/字面值，公式无缓存时返回 None（绝不返回公式文本当金额）。"""
        info = self.cells.get((row, col))
        if info is None:
            return None
        return info.value

    def merged_anchor(self, row: int, col: int) -> tuple[int, int] | None:
        """若单元格属于某个合并区域，返回该区域左上角坐标。"""
        for m in self.merges:
            if m.contains(row, col):
                return m.min_row, m.min_col
        return None


@dataclasses.dataclass
class WorkbookGrid:
    path: str
    sheets: dict[str, SheetGrid]

    @property
    def sheet_names(self) -> list[str]:
        return list(self.sheets.keys())


def load_workbook_grid(path: str | Path) -> WorkbookGrid:
    """读取工作簿。公式视图 + 缓存值视图各打开一次。"""
    path = str(path)
    wb_formula = openpyxl.load_workbook(path, data_only=False, read_only=False)
    wb_values = openpyxl.load_workbook(path, data_only=True, read_only=False)

    sheets: dict[str, SheetGrid] = {}
    for ws_f in wb_formula.worksheets:
        ws_v: Worksheet = wb_values[ws_f.title]
        cells: dict[tuple[int, int], CellInfo] = {}
        max_row = max(ws_f.max_row or 1, ws_v.max_row or 1)
        max_col = max(ws_f.max_column or 1, ws_v.max_column or 1)

        for row in ws_f.iter_rows():
            for cell_f in row:
                r, c = cell_f.row, cell_f.column
                cell_v = ws_v.cell(row=r, column=c)
                raw = cell_f.value
                cached = cell_v.value
                is_formula = isinstance(raw, str) and raw.startswith("=")
                if is_formula:
                    # 缓存视图里公式格的值为 None 即“没有缓存”；
                    # 单元格仍需保留（标记无缓存），不能直接丢弃
                    has_cache = cached is not None
                    value = cached if has_cache else None
                else:
                    has_cache = False
                    value = raw
                if raw is None and cached is None:
                    continue
                cells[(r, c)] = CellInfo(
                    row=r, col=c, value=value, raw=raw,
                    is_formula=is_formula, has_cached_value=has_cache,
                )

        merges: list[MergeRange] = []
        merge_topleft: dict[tuple[int, int, int, int], Any] = {}
        for mr in ws_f.merged_cells.ranges:
            m = MergeRange(mr.min_row, mr.max_row, mr.min_col, mr.max_col)
            merges.append(m)
            anchor = cells.get((m.min_row, m.min_col))
            merge_topleft[(m.min_row, m.max_row, m.min_col, m.max_col)] = (
                anchor.value if anchor is not None else None
            )

        sheets[ws_f.title] = SheetGrid(
            name=ws_f.title, max_row=max_row, max_col=max_col,
            cells=cells, merges=merges, merge_topleft=merge_topleft,
        )

    wb_formula.close()
    wb_values.close()
    return WorkbookGrid(path=path, sheets=sheets)
