"""核心展开引擎：多层表头 -> 明细记录，并产出问题清单与合计核对结果。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .grid import WorkbookGrid
from .models import (
    MappingConfig,
    parse_amount,
    parse_month,
    row_skip_reason,
)
from .ranges import fill_merges_in_scope, to_a1


@dataclass
class HeaderColumn:
    col: int
    path: list[str]                 # 多层表头自上而下的值
    month: str                      # YYYY-MM
    month_display: str
    channel: str                    # 标准渠道名
    channel_raw: str


@dataclass
class Issue:
    severity: str                   # error / warning / info
    code: str
    coordinate: str                 # 工作簿坐标，如 Sheet1!C12
    message: str
    raw: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity, "code": self.code,
            "coordinate": self.coordinate, "message": self.message,
            "raw": None if self.raw is None else str(self.raw),
        }


@dataclass
class DetailRecord:
    dimensions: dict[str, str]
    month: str
    channel: str
    amount_yuan: float | None
    unit: str
    value_source: str               # literal / formula_cache / missing / unparseable
    workbook_path: str
    sheet_name: str
    coordinate: str
    row: int
    col: int
    formula_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "month": self.month,
            "channel": self.channel,
            "amount_yuan": self.amount_yuan,
            "unit": self.unit,
            "value_source": self.value_source,
            "workbook_path": self.workbook_path,
            "sheet_name": self.sheet_name,
            "coordinate": self.coordinate,
            "row": self.row,
            "col": self.col,
            "formula_text": self.formula_text,
        }


@dataclass
class TotalRow:
    row: int
    label: str
    kind: str                       # total / note
    # 列号 -> 原始单元格信息（金额状态在核对阶段解析）
    values: dict[int, Any]
    coordinates: dict[int, str]


@dataclass
class ReconciliationItem:
    label: str
    total_row: int
    coordinate: str
    month: str
    channel: str
    source_amount: float | None
    computed_amount: float | None
    diff: float | None
    matched: bool
    detail_row_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "total_row": self.total_row,
            "coordinate": self.coordinate, "month": self.month,
            "channel": self.channel, "source_amount": self.source_amount,
            "computed_amount": self.computed_amount, "diff": self.diff,
            "matched": self.matched, "detail_row_count": self.detail_row_count,
        }


@dataclass
class ExtractResult:
    records: list[DetailRecord]
    issues: list[Issue]
    total_rows: list[TotalRow]
    reconciliation: list[ReconciliationItem]
    header_columns: list[HeaderColumn]
    fingerprint: str

    def summary(self) -> dict[str, Any]:
        return {
            "record_count": len(self.records),
            "issue_count": len(self.issues),
            "error_count": sum(1 for i in self.issues if i.severity == "error"),
            "total_row_count": len(self.total_rows),
            "reconcile_mismatch_count": sum(
                1 for r in self.reconciliation if not r.matched
            ),
        }


def _coord(sheet: str, row: int, col: int) -> str:
    return f"{sheet}!{to_a1(row, col)}"


def compute_fingerprint(grid, header_rect: tuple[int, int, int, int],
                        dims, filled: dict[tuple[int, int], object]) -> str:
    """结构指纹：表头区域填充后的二维文本 + 维度列定义。

    下一期复用映射时，指纹不一致即停在预览确认。
    """
    r1, r2, c1, c2 = header_rect
    matrix = [
        [str(filled.get((r, c), "")) for c in range(c1, c2 + 1)]
        for r in range(r1, r2 + 1)
    ]
    payload = json.dumps(
        {"header": matrix,
         "dims": [(d.col, d.name) for d in dims]},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_header_columns(
    grid, cfg: MappingConfig, filled: dict[tuple[int, int], object],
    issues: list[Issue],
) -> list[HeaderColumn]:
    r1, r2, c1, c2 = cfg.header.as_tuple()
    dim_col_set = {d.col for d in cfg.dim_columns()}
    columns: list[HeaderColumn] = []
    for c in range(c1, c2 + 1):
        # 表头区域可能同时框住了维度列（如 A2:A3 的“区域”），跳过它们
        if c in dim_col_set:
            continue
        path: list[str] = []
        for r in range(r1, r2 + 1):
            val = filled.get((r, c))
            text = "" if val is None else str(val).strip()
            if text and (not path or path[-1] != text):
                path.append(text)
        if not path:
            issues.append(Issue(
                "error", "empty_header", _coord(cfg.sheet_name, r1, c),
                f"第 {c} 列表头为空，已跳过该列",
            ))
            continue

        # 月份：路径中第一个可解析为月份的组件。
        # 路径里允许存在“季度”等非月份层级，只有整条路径都找不到月份才报错。
        month, month_display, month_component = None, None, None
        uncertain_parts: list[str] = []
        for part in path:
            status, iso, display = parse_month(part, cfg.report_year)
            if status == "ok":
                month, month_display, month_component = iso, display, part
                break
            if status == "uncertain":
                uncertain_parts.append(part)
        if month is None:
            if uncertain_parts:
                issues.append(Issue(
                    "error", "uncertain_month", _coord(cfg.sheet_name, r1, c),
                    f"表头月份无法确认: {uncertain_parts[0]!r}，该列需人工处理后再展开",
                    uncertain_parts[0],
                ))
            else:
                issues.append(Issue(
                    "error", "month_not_found", _coord(cfg.sheet_name, r1, c),
                    f"表头 {path} 中未找到月份，已跳过该列", " / ".join(path),
                ))
            continue

        # 渠道：优先取路径中独立的非月份组件（多层表头的最下层）；
        # 单层复合表头（如 “3月-线上”）则从月份组件里抽取线上/线下关键字
        channel_raw = ""
        for part in reversed(path):
            if part != month_component:
                channel_raw = part
                break
        if not channel_raw:
            for kw in ("线上", "线下"):
                if kw in month_component:
                    channel_raw = kw
                    break
        channel = cfg.channel_aliases.get(channel_raw, channel_raw) or "未标注"

        columns.append(HeaderColumn(
            col=c, path=path, month=month, month_display=month_display or "",
            channel=channel, channel_raw=channel_raw,
        ))
    return columns


def extract(wb: WorkbookGrid, cfg: MappingConfig) -> ExtractResult:
    if cfg.sheet_name not in wb.sheets:
        raise ValueError(f"工作簿中不存在工作表: {cfg.sheet_name}")
    grid = wb.sheets[cfg.sheet_name]
    dims = cfg.dim_columns()
    header_rect = cfg.header.as_tuple()
    filled = fill_merges_in_scope(grid, header_rect, dims)
    fingerprint = compute_fingerprint(grid, header_rect, dims, filled)

    issues: list[Issue] = []
    hc = build_header_columns(grid, cfg, filled, issues)

    d = cfg.data
    if (d.col_start, d.col_end) != (cfg.header.col_start, cfg.header.col_end):
        issues.append(Issue(
            "warning", "data_header_col_mismatch",
            _coord(cfg.sheet_name, d.row_start, d.col_start),
            "数据区域列范围与表头列范围不一致，按表头列展开",
        ))

    records: list[DetailRecord] = []
    total_rows: list[TotalRow] = []
    # 核对用：自上个合计行以来的明细索引，以及全部明细索引
    detail_buffer: list[int] = []
    all_detail: list[int] = []

    for r in range(d.row_start, d.row_end + 1):
        dim_values: dict[str, str] = {}
        dim_texts: list[str] = []
        for idx, dim in enumerate(dims):
            val = filled.get((r, dim.col))
            text = "" if val is None else str(val).strip()
            dim_name = dim.name or f"维度{idx + 1}"
            dim_values[dim_name] = text
            dim_texts.append(text)

        # 合计/小计/备注可能出现在任意维度列（区域列常为合并留空），
        # 取第一个命中关键字的维度文本
        skip, first_text = None, dim_texts[0] if dim_texts else ""
        for text in dim_texts:
            reason = row_skip_reason(text)
            if reason is not None:
                skip, first_text = reason, text
                break
        if skip is not None:
            vals: dict[int, Any] = {}
            coords: dict[int, str] = {}
            for hcol in hc:
                info = grid.get(r, hcol.col)
                vals[hcol.col] = info.value if info else None
                coords[hcol.col] = _coord(cfg.sheet_name, r, hcol.col)
                # 合计行的无缓存公式同样阻断核对：登记 issue，绝不拿公式文本当金额
                if info is not None and info.is_formula and not info.has_cached_value:
                    issues.append(Issue(
                        "error", "formula_without_cache",
                        coords[hcol.col],
                        "合计单元格是无缓存值公式，无法读取原表合计；"
                        "请在 Excel 中打开并保存后重新导入",
                        info.raw,
                    ))
            total_rows.append(TotalRow(
                row=r, label=first_text or f"第{r}行", kind=skip,
                values=vals, coordinates=coords,
            ))
            if skip == "note":
                issues.append(Issue(
                    "info", "note_row_skipped",
                    _coord(cfg.sheet_name, r, dims[0].col if dims else 1),
                    f"备注/说明行已跳过: {first_text}", first_text,
                ))
            # 合计/备注行不产出明细，也不进入核对缓冲
            continue

        # 完全空白行（所有维度与数据格都空）跳过，不计明细
        row_has_content = any(v != "" for v in dim_values.values()) or any(
            grid.get(r, hcol.col) is not None for hcol in hc
        )
        if not row_has_content:
            continue

        for hcol in hc:
            info = grid.get(r, hcol.col)
            raw_value = info.value if info else None
            formula_text = info.raw if (info and info.is_formula) else None
            coordinate = _coord(cfg.sheet_name, r, hcol.col)

            if info is not None and info.is_formula and not info.has_cached_value:
                issues.append(Issue(
                    "error", "formula_without_cache", coordinate,
                    "公式没有缓存值，无法读取金额（不会用公式文本充当金额）；"
                    "请在 Excel 中打开并保存后重新导入",
                    formula_text,
                ))
                amount, source = None, "formula_no_cache"
            elif info is not None and info.is_formula:
                amount, status = parse_amount(raw_value, cfg.unit)
                if status != "ok":
                    issues.append(Issue(
                        "error", f"formula_cache_{status}", coordinate,
                        f"公式缓存值无法解析为金额: {raw_value!r}", raw_value,
                    ))
                    source = "unparseable"
                else:
                    source = "formula_cache"
            else:
                amount, status = parse_amount(raw_value, cfg.unit)
                if status == "missing":
                    source = "missing"
                elif status == "unparseable":
                    issues.append(Issue(
                        "error", "unparseable_amount", coordinate,
                        f"单元格值无法解析为金额: {raw_value!r}", raw_value,
                    ))
                    source = "unparseable"
                elif status == "formula_without_cache":
                    issues.append(Issue(
                        "error", "formula_without_cache", coordinate,
                        "检测到公式文本但无缓存值，请在 Excel 中保存后重新导入",
                        raw_value,
                    ))
                    source = "formula_no_cache"
                else:
                    source = "literal"

            rec = DetailRecord(
                dimensions=dict(dim_values),
                month=hcol.month,
                channel=hcol.channel,
                amount_yuan=amount,
                unit=cfg.unit,
                value_source=source,
                workbook_path=wb.path,
                sheet_name=cfg.sheet_name,
                coordinate=coordinate,
                row=r, col=hcol.col,
                formula_text=formula_text,
            )
            records.append(rec)
            detail_buffer.append(len(records) - 1)
            all_detail.append(len(records) - 1)

    reconciliation = _reconcile(
        records, total_rows, hc, cfg, detail_buffer, all_detail,
    )
    return ExtractResult(
        records=records, issues=issues, total_rows=total_rows,
        reconciliation=reconciliation, header_columns=hc,
        fingerprint=fingerprint,
    )


def _reconcile(
    records: list[DetailRecord],
    total_rows: list[TotalRow],
    hc: list[HeaderColumn],
    cfg: MappingConfig,
    detail_buffer: list[int],
    all_detail: list[int],
) -> list[ReconciliationItem]:
    """原表合计 vs 展开明细核对。

    - “总计/总合计/合计”行：与全部明细比；
    - 其他合计/小计行：与上一个合计行之后、且位于本行之前的明细比。
    作用域按单元格行号界定，避免缓冲在整表收集后无法回溯。
    容差 0.01 元（覆盖万元换算后的舍入）。
    """
    items: list[ReconciliationItem] = []
    last_total_row = 0
    col_by_num = {h.col: h for h in hc}

    for tr in total_rows:
        if tr.kind != "total":
            continue
        is_grand = ("总计" in tr.label) or ("总合计" in tr.label) or tr.label == "合计"
        if is_grand:
            scope = list(all_detail)
        else:
            scope = [
                i for i in all_detail
                if last_total_row < records[i].row < tr.row
            ]
        for col, raw in tr.values.items():
            hcol = col_by_num.get(col)
            if hcol is None:
                continue
            source_amt, status = parse_amount(raw, cfg.unit)
            if status in ("missing", "unparseable", "formula_without_cache"):
                items.append(ReconciliationItem(
                    label=tr.label, total_row=tr.row,
                    coordinate=tr.coordinates[col], month=hcol.month,
                    channel=hcol.channel, source_amount=None,
                    computed_amount=None, diff=None, matched=False,
                    detail_row_count=sum(
                        1 for i in scope
                        if records[i].month == hcol.month
                        and records[i].channel == hcol.channel
                    ),
                ))
                continue
            scoped = [
                records[i] for i in scope
                if records[i].month == hcol.month
                and records[i].channel == hcol.channel
            ]
            computed = sum((rec.amount_yuan or 0.0) for rec in scoped)
            cnt = len(scoped)
            diff = round((source_amt or 0.0) - computed, 2)
            items.append(ReconciliationItem(
                label=tr.label, total_row=tr.row,
                coordinate=tr.coordinates[col], month=hcol.month,
                channel=hcol.channel, source_amount=round(source_amt, 2),
                computed_amount=round(computed, 2), diff=diff,
                matched=abs(diff) <= 0.01, detail_row_count=cnt,
            ))
        if not is_grand:
            last_total_row = tr.row
    return items
