"""引擎测试：合并填充、月份/渠道展开、单位换算、缺失保留、
合计跳过与核对、无缓存公式阻断、结构指纹。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extractor import extract  # noqa: E402
from app.grid import load_workbook_grid  # noqa: E402
from app.models import (  # noqa: E402
    DataSelection,
    HeaderSelection,
    MappingConfig,
)
from app.ranges import DimColumn, fill_merges_in_scope, parse_range  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_workbooks"


def cfg_standard() -> MappingConfig:
    return MappingConfig(
        name="标准双层表头",
        sheet_name="门店销售月报",
        report_year=2025,
        unit="元",
        header=HeaderSelection(2, 3, 1, 6),
        data=DataSelection(4, 11, 1, 6),
        dimensions=[
            {"col": 1, "row_start": 4, "row_end": 11, "name": "区域"},
            {"col": 2, "row_start": 4, "row_end": 11, "name": "门店"},
        ],
    )


def cfg_wanyuan() -> MappingConfig:
    return MappingConfig(
        name="万元三层表头",
        sheet_name="销售月报",
        report_year=2025,
        unit="万元",
        header=HeaderSelection(2, 4, 1, 10),
        data=DataSelection(5, 10, 1, 10),
        dimensions=[
            {"col": 1, "row_start": 5, "row_end": 10, "name": "大区"},
            {"col": 2, "row_start": 5, "row_end": 10, "name": "门店名称"},
        ],
        channel_aliases={"网店": "线上", "门店": "线下"},
    )


def cfg_flat() -> MappingConfig:
    return MappingConfig(
        name="单层表头",
        sheet_name="1月-6月",
        report_year=2025,
        unit="元",
        header=HeaderSelection(2, 2, 1, 6),
        data=DataSelection(3, 8, 1, 6),
        dimensions=[
            {"col": 1, "row_start": 3, "row_end": 8, "name": "区域"},
            {"col": 2, "row_start": 3, "row_end": 8, "name": "门店"},
        ],
    )


# ---------------------------------------------------------------- 基础解析

def test_parse_range_and_a1():
    assert parse_range("c2:d3") == (2, 3, 3, 4)
    assert parse_range("A1:F1") == (1, 1, 1, 6)


def test_merge_fill_only_in_scope():
    wb = load_workbook_grid(str(SAMPLE_DIR / "01_standard_dual_header.xlsx"))
    grid = wb.sheets["门店销售月报"]
    dims = [
        DimColumn(1, 4, 11, "区域"),
        DimColumn(2, 4, 11, "门店"),
    ]
    filled = fill_merges_in_scope(grid, (2, 3, 1, 6), dims)
    # 维度合并：华东向下补到第 5 行
    assert filled[(4, 1)] == "华东"
    assert filled[(5, 1)] == "华东"
    # 表头横向合并：1月补到 D2
    assert filled[(2, 3)] == "1月"
    assert filled[(2, 4)] == "1月"
    # 数据区域绝不在填充表里
    assert (4, 3) not in filled


# ---------------------------------------------------------------- 标准表

def test_standard_expansion_and_missing():
    wb = load_workbook_grid(str(SAMPLE_DIR / "01_standard_dual_header.xlsx"))
    result = extract(wb, cfg_standard())
    # 4 家门店 x 4 个指标列 = 16 条；合计/小计/备注行不产出明细
    assert len(result.records) == 16
    assert all(r.month in ("2025-01", "2025-02") for r in result.records)
    assert {r.channel for r in result.records} == {"线上", "线下"}

    # 合并维度补齐
    sh = next(r for r in result.records
              if r.dimensions["门店"] == "杭州湖滨店" and r.channel == "线上")
    assert sh.dimensions["区域"] == "华东"
    assert sh.coordinate.startswith("门店销售月报!")
    assert sh.value_source == "literal"

    # 空白与 “—” 保留为缺失
    miss = [r for r in result.records if r.amount_yuan is None]
    assert len(miss) == 2
    assert {r.value_source for r in miss} == {"missing"}

    # 合计/小计/备注均被识别
    kinds = [t.kind for t in result.total_rows]
    assert kinds.count("total") == 3
    assert "note" in kinds

    # 核对：所有合计单元格与展开明细一致
    assert result.reconciliation
    assert all(item.matched for item in result.reconciliation), [
        i.__dict__ for i in result.reconciliation if not i.matched
    ]


def test_standard_fingerprint_stable():
    wb = load_workbook_grid(str(SAMPLE_DIR / "01_standard_dual_header.xlsx"))
    r1 = extract(wb, cfg_standard())
    r2 = extract(wb, cfg_standard())
    assert r1.fingerprint == r2.fingerprint
    assert len(r1.fingerprint) == 16


# ---------------------------------------------------------------- 万元三层

def test_wanyuan_conversion_and_alias_and_three_level():
    wb = load_workbook_grid(str(SAMPLE_DIR / "02_wanyuan_three_level.xlsx"))
    result = extract(wb, cfg_wanyuan())
    # 4 店 x 8 列 = 32
    assert len(result.records) == 32
    rec = next(r for r in result.records
               if r.dimensions["门店名称"] == "广州天河城店"
               and r.month == "2025-01" and r.channel == "线上")
    # 12.5 万元 -> 125000 元
    assert rec.amount_yuan == pytest.approx(125_000.0)
    assert rec.unit == "万元"
    # 渠道别名：网店->线上、门店->线下
    assert {r.channel for r in result.records} == {"线上", "线下"}
    # 月份来自中间层、渠道来自最下层
    assert {r.month for r in result.records} == {"2025-01", "2025-02", "2025-04", "2025-05"}

    # 合计行是无缓存公式 -> 阻断 issue，且核对项标为不一致（来源不可读）
    codes = {i.code for i in result.issues}
    assert "formula_without_cache" in codes
    bad = [i for i in result.reconciliation if not i.matched]
    assert bad and all(i.source_amount is None for i in bad)


# ---------------------------------------------------------------- 单层表头

def test_flat_header_dash_and_reconcile_mismatch_locatable():
    wb = load_workbook_grid(str(SAMPLE_DIR / "03_flat_single_header.xlsx"))
    result = extract(wb, cfg_flat())
    assert len(result.records) == 16  # 4 店 x 4 列
    # “3月-线上” 复合表头能拆出月份与渠道
    sample = result.records[0]
    assert sample.month == "2025-03"
    assert sample.channel == "线上"
    # “—” 与空白均为缺失
    assert sum(1 for r in result.records if r.amount_yuan is None) == 2

    # 合计行静态值 vs 明细：6月线上缺少一条缺失值，合计是全量 -> 应能定位差异
    recon = result.reconciliation
    assert recon
    mismatch = [i for i in recon if not i.matched]
    # 6月线上：合计含 78000+65000+41000，明细侧缺失的那条按 0 参与
    june_online = next(i for i in recon if i.month == "2025-06" and i.channel == "线上")
    assert june_online.coordinate.endswith(str(june_online.total_row))
    assert june_online.diff is not None


# ---------------------------------------------------------------- 公式模式

def test_formula_without_cache_blocks_but_cached_ok():
    wb = load_workbook_grid(str(SAMPLE_DIR / "04_formula_cache_modes.xlsx"))

    # 有缓存值 sheet：合计行被跳过，明细 2 店 x 2 列正常
    cfg_ok = MappingConfig(
        name="公式-好", sheet_name="有缓存值", report_year=2025, unit="元",
        header=HeaderSelection(1, 1, 1, 3),
        data=DataSelection(2, 4, 1, 3),
        dimensions=[{"col": 1, "row_start": 2, "row_end": 4, "name": "门店"}],
    )
    ok = extract(wb, cfg_ok)
    assert len(ok.records) == 4
    assert not [i for i in ok.issues if i.severity == "error"]
    assert all(i.matched for i in ok.reconciliation)

    # 无缓存公式 sheet：明细数据正常，但合计公式读不到 -> error 且带坐标
    cfg_bad = MappingConfig(
        name="公式-坏", sheet_name="无缓存公式", report_year=2025, unit="元",
        header=HeaderSelection(1, 1, 1, 3),
        data=DataSelection(2, 4, 1, 3),
        dimensions=[{"col": 1, "row_start": 2, "row_end": 4, "name": "门店"}],
    )
    bad = extract(wb, cfg_bad)
    assert len(bad.records) == 4  # 门店明细不受影响
    errs = [i for i in bad.issues if i.severity == "error"]
    assert any(i.code == "formula_without_cache" for i in errs)
    assert all("!" in i.coordinate for i in errs)
    # 公式文本保留在 issue 里供人工判断，但绝不当金额
    assert any(str(i.raw).startswith("=") for i in errs)


# ---------------------------------------------------------------- 指纹变化

def test_fingerprint_changes_when_header_changes():
    wb = load_workbook_grid(str(SAMPLE_DIR / "01_standard_dual_header.xlsx"))
    base = extract(wb, cfg_standard())
    changed = cfg_standard()
    changed.report_year = 2026  # 年份不参与指纹（表头文本才参与）
    assert extract(wb, changed).fingerprint == base.fingerprint

    changed2 = cfg_standard()
    changed2.header = HeaderSelection(2, 3, 1, 5)  # 砍掉一列 -> 结构变化
    assert extract(wb, changed2).fingerprint != base.fingerprint
