"""DuckDB 落地层。所有表都带工作簿/工作表/单元格坐标，支持点回原表。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from .extractor import ExtractResult

DEFAULT_DB_PATH = os.environ.get(
    "REPORT_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "duckdb" / "report.duckdb")
)

SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS seq_fact START 1;
CREATE SEQUENCE IF NOT EXISTS seq_issue START 1;
CREATE SEQUENCE IF NOT EXISTS seq_recon START 1;

CREATE TABLE IF NOT EXISTS fact_store_sales (
    id BIGINT DEFAULT nextval('seq_fact'),
    import_id VARCHAR NOT NULL,
    workbook_path VARCHAR NOT NULL,
    workbook_name VARCHAR NOT NULL,
    sheet_name VARCHAR NOT NULL,
    cell_row INTEGER NOT NULL,
    cell_col INTEGER NOT NULL,
    cell_coordinate VARCHAR NOT NULL,
    dim_region VARCHAR,
    dim_store VARCHAR,
    dimensions_json VARCHAR NOT NULL,
    report_month VARCHAR NOT NULL,
    channel VARCHAR NOT NULL,
    amount_yuan DOUBLE,
    unit VARCHAR NOT NULL,
    value_source VARCHAR NOT NULL,
    formula_text VARCHAR,
    imported_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batch (
    import_id VARCHAR PRIMARY KEY,
    workbook_name VARCHAR NOT NULL,
    workbook_path VARCHAR NOT NULL,
    sheet_name VARCHAR NOT NULL,
    mapping_name VARCHAR,
    mapping_fingerprint VARCHAR,
    report_year INTEGER NOT NULL,
    unit VARCHAR NOT NULL,
    record_count INTEGER NOT NULL,
    issue_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL,
    mismatch_count INTEGER NOT NULL,
    imported_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS mapping_config (
    name VARCHAR PRIMARY KEY,
    sheet_name VARCHAR NOT NULL,
    report_year INTEGER NOT NULL,
    unit VARCHAR NOT NULL,
    config_json VARCHAR NOT NULL,
    fingerprint VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS import_issue (
    id BIGINT DEFAULT nextval('seq_issue'),
    import_id VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    coordinate VARCHAR NOT NULL,
    message VARCHAR NOT NULL,
    raw_value VARCHAR
);

CREATE TABLE IF NOT EXISTS reconciliation (
    id BIGINT DEFAULT nextval('seq_recon'),
    import_id VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    total_row INTEGER NOT NULL,
    coordinate VARCHAR NOT NULL,
    report_month VARCHAR NOT NULL,
    channel VARCHAR NOT NULL,
    source_amount DOUBLE,
    computed_amount DOUBLE,
    diff DOUBLE,
    matched BOOLEAN NOT NULL,
    detail_row_count INTEGER NOT NULL
);
"""


class Storage:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.db_path)
        self.con.execute(SCHEMA)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------- 映射 ----------------
    def save_mapping(self, cfg_dict: dict[str, Any], fingerprint: str) -> None:
        now = datetime.now()
        self.con.execute(
            """
            INSERT OR REPLACE INTO mapping_config
                (name, sheet_name, report_year, unit, config_json, fingerprint,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?,
                    COALESCE((SELECT created_at FROM mapping_config WHERE name = ?), ?),
                    ?)
            """,
            [
                cfg_dict["name"], cfg_dict["sheet_name"], cfg_dict["report_year"],
                cfg_dict["unit"], json.dumps(cfg_dict, ensure_ascii=False),
                fingerprint, cfg_dict["name"], now, now,
            ],
        )

    def list_mappings(self) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT name, sheet_name, report_year, unit, fingerprint, updated_at "
            "FROM mapping_config ORDER BY updated_at DESC"
        ).fetchall()
        return [
            {
                "name": r[0], "sheet_name": r[1], "report_year": r[2],
                "unit": r[3], "fingerprint": r[4],
                "updated_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]

    def get_mapping(self, name: str) -> dict[str, Any] | None:
        row = self.con.execute(
            "SELECT config_json, fingerprint FROM mapping_config WHERE name = ?",
            [name],
        ).fetchone()
        if row is None:
            return None
        return {"config": json.loads(row[0]), "fingerprint": row[1]}

    # ---------------- 导入批次与明细 ----------------
    def commit_import(
        self,
        import_id: str,
        workbook_path: str,
        workbook_name: str,
        mapping_name: str,
        cfg_dict: dict[str, Any],
        fingerprint: str,
        result: ExtractResult,
    ) -> dict[str, Any]:
        now = datetime.now()
        summary = result.summary()
        self.con.execute(
            """
            INSERT INTO import_batch
                (import_id, workbook_name, workbook_path, sheet_name,
                 mapping_name, mapping_fingerprint, report_year, unit,
                 record_count, issue_count, error_count, mismatch_count,
                 imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                import_id, workbook_name, workbook_path, cfg_dict["sheet_name"],
                mapping_name, fingerprint, cfg_dict["report_year"], cfg_dict["unit"],
                summary["record_count"], summary["issue_count"],
                summary["error_count"], summary["reconcile_mismatch_count"], now,
            ],
        )

        dims_meta = cfg_dict["dimensions"]

        def dim_of(dims_json: dict[str, str], key: str) -> str | None:
            return dims_json.get(key)

        fact_rows = []
        for rec in result.records:
            dims_json = json.dumps(rec.dimensions, ensure_ascii=False)
            # 约定：前两个维度按顺序作为 region/store（不存在则 NULL）
            vals = list(rec.dimensions.values())
            dim_region = vals[0] if vals else None
            dim_store = vals[1] if len(vals) > 1 else None
            fact_rows.append((
                import_id, rec.workbook_path, workbook_name, rec.sheet_name,
                rec.row, rec.col, rec.coordinate, dim_region, dim_store,
                dims_json, rec.month, rec.channel, rec.amount_yuan, rec.unit,
                rec.value_source, rec.formula_text, now,
            ))
        if fact_rows:
            self.con.executemany(
                """
                INSERT INTO fact_store_sales
                    (import_id, workbook_path, workbook_name, sheet_name,
                     cell_row, cell_col, cell_coordinate, dim_region, dim_store,
                     dimensions_json, report_month, channel, amount_yuan, unit,
                     value_source, formula_text, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                fact_rows,
            )

        # DuckDB 的 executemany 不接受空参数列表，无对应数据时跳过插入
        if result.issues:
            self.con.executemany(
                """
                INSERT INTO import_issue
                    (import_id, severity, code, coordinate, message, raw_value)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (import_id, i.severity, i.code, i.coordinate, i.message,
                     None if i.raw is None else str(i.raw))
                    for i in result.issues
                ],
            )

        if result.reconciliation:
            self.con.executemany(
                """
                INSERT INTO reconciliation
                    (import_id, label, total_row, coordinate, report_month, channel,
                     source_amount, computed_amount, diff, matched, detail_row_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (import_id, r.label, r.total_row, r.coordinate, r.month,
                     r.channel, r.source_amount, r.computed_amount, r.diff,
                     r.matched, r.detail_row_count)
                    for r in result.reconciliation
                ],
            )
        return summary

    # ---------------- 查询 ----------------
    def list_imports(self) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM import_batch ORDER BY imported_at DESC"
        ).fetchall()
        cols = [d[0] for d in self.con.description]
        out = []
        for r in rows:
            item = dict(zip(cols, r))
            item["imported_at"] = item["imported_at"].isoformat()
            out.append(item)
        return out

    def query_facts(
        self, import_id: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        if import_id:
            rows = self.con.execute(
                "SELECT * FROM fact_store_sales WHERE import_id = ? "
                "ORDER BY id LIMIT ?",
                [import_id, limit],
            ).fetchall()
        else:
            rows = self.con.execute(
                "SELECT * FROM fact_store_sales ORDER BY id DESC LIMIT ?",
                [limit],
            ).fetchall()
        cols = [d[0] for d in self.con.description]
        return [dict(zip(cols, r)) for r in rows]

    def get_reconciliation(self, import_id: str) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM reconciliation WHERE import_id = ? "
            "ORDER BY total_row, report_month, channel",
            [import_id],
        ).fetchall()
        cols = [d[0] for d in self.con.description]
        return [dict(zip(cols, r)) for r in rows]

    def get_issues(self, import_id: str) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT severity, code, coordinate, message, raw_value "
            "FROM import_issue WHERE import_id = ? ORDER BY id",
            [import_id],
        ).fetchall()
        return [
            dict(zip(["severity", "code", "coordinate", "message", "raw_value"], r))
            for r in rows
        ]
