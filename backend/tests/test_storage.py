"""DuckDB 入仓测试：批次、明细溯源、问题、核对、映射复用。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extractor import extract  # noqa: E402
from app.grid import load_workbook_grid  # noqa: E402
from app.storage import Storage  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_workbooks"


def _cfg():
    from app.models import DataSelection, HeaderSelection, MappingConfig
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


def test_full_import_and_lineage(tmp_path):
    db = tmp_path / "t.duckdb"
    wb_path = SAMPLE_DIR / "01_standard_dual_header.xlsx"
    wb = load_workbook_grid(str(wb_path))
    cfg = _cfg()
    result = extract(wb, cfg)

    with Storage(str(db)) as st:
        st.save_mapping(cfg.to_dict(), result.fingerprint)
        summary = st.commit_import(
            import_id="imp-1", workbook_path=str(wb_path),
            workbook_name=wb_path.name, mapping_name=cfg.name,
            cfg_dict=cfg.to_dict(), fingerprint=result.fingerprint,
            result=result,
        )
        assert summary["record_count"] == 16
        assert summary["error_count"] == 0

        facts = st.query_facts("imp-1")
        assert len(facts) == 16
        # 每条记录都能点回工作簿、工作表、坐标
        first = facts[0]
        assert first["workbook_name"] == wb_path.name
        assert first["sheet_name"] == "门店销售月报"
        assert "!" in first["cell_coordinate"]
        assert first["cell_row"] >= 4 and first["cell_col"] >= 3
        # 维度补齐后落仓
        assert first["dim_region"] in ("华东", "华北")
        assert first["dim_store"]

        recon = st.get_reconciliation("imp-1")
        assert recon and all(r["matched"] for r in recon)

        saved = st.get_mapping("标准双层表头")
        assert saved is not None
        assert saved["fingerprint"] == result.fingerprint
        assert saved["config"]["unit"] == "元"

        batches = st.list_imports()
        assert len(batches) == 1 and batches[0]["import_id"] == "imp-1"


def test_commit_with_zero_issues_and_zero_recon(tmp_path):
    """没有问题/核对项时，空列表不能让 DuckDB executemany 报错（回归）。"""
    db = tmp_path / "empty.duckdb"
    wb_path = SAMPLE_DIR / "04_formula_cache_modes.xlsx"
    wb = load_workbook_grid(str(wb_path))
    from app.models import DataSelection, HeaderSelection, MappingConfig
    cfg = MappingConfig(
        name="无问题表", sheet_name="有缓存值", report_year=2025, unit="元",
        header=HeaderSelection(1, 1, 1, 3),
        data=DataSelection(2, 3, 1, 3),   # 只含门店明细，不含合计行
        dimensions=[{"col": 1, "row_start": 2, "row_end": 3, "name": "门店"}],
    )
    result = extract(wb, cfg)
    assert result.issues == []
    assert result.reconciliation == []
    with Storage(str(db)) as st:
        summary = st.commit_import(
            import_id="imp-2", workbook_path=str(wb_path),
            workbook_name=wb_path.name, mapping_name=cfg.name,
            cfg_dict=cfg.to_dict(), fingerprint=result.fingerprint,
            result=result,
        )
        assert summary["record_count"] == 4
        assert st.query_facts("imp-2") and st.get_issues("imp-2") == []


def test_import_blocked_on_errors_still_detectable(tmp_path):
    """无缓存公式工作簿：提取产生 error 级 issue（API 层据此拒绝入仓）。"""
    wb = load_workbook_grid(str(SAMPLE_DIR / "02_wanyuan_three_level.xlsx"))
    from app.models import DataSelection, HeaderSelection, MappingConfig
    cfg = MappingConfig(
        name="万元", sheet_name="销售月报", report_year=2025, unit="万元",
        header=HeaderSelection(2, 4, 1, 10),
        data=DataSelection(5, 10, 1, 10),
        dimensions=[
            {"col": 1, "row_start": 5, "row_end": 10, "name": "大区"},
            {"col": 2, "row_start": 5, "row_end": 10, "name": "门店名称"},
        ],
        channel_aliases={"网店": "线上", "门店": "线下"},
    )
    result = extract(wb, cfg)
    assert any(i.severity == "error" and i.code == "formula_without_cache"
               for i in result.issues)
