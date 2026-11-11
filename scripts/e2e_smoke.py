"""端到端冒烟：对 4 份示例工作簿依次上传 -> 试展开 -> 入仓/阻断校验。

运行：.venv/bin/python -I scripts/e2e_smoke.py
依赖运行中的后端（默认 http://127.0.0.1:8000）。
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"
SAMPLE = Path(__file__).resolve().parents[1] / "sample_workbooks"


def post_json(path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def upload(path: Path) -> str:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/workbooks/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["workbook_id"]


def rect(r1, r2, c1, c2):
    return {"row_start": r1, "row_end": r2, "col_start": c1, "col_end": c2}


def dim(col, r1, r2, name):
    return {"col": col, "row_start": r1, "row_end": r2, "name": name}


CASES = [
    {
        "file": "01_standard_dual_header.xlsx",
        "expect_commit": True,
        "mapping": {
            "name": "e2e-标准双层", "sheet_name": "门店销售月报",
            "report_year": 2025, "unit": "元",
            "header": rect(2, 3, 1, 6), "data": rect(4, 11, 1, 6),
            "dimensions": [dim(1, 4, 11, "区域"), dim(2, 4, 11, "门店")],
            "channel_aliases": {},
        },
        "checks": {"records": 16, "errors": 0, "mismatch": 0},
    },
    {
        "file": "02_wanyuan_three_level.xlsx",
        "expect_commit": False,   # 无缓存公式 -> 422
        "mapping": {
            "name": "e2e-万元三层", "sheet_name": "销售月报",
            "report_year": 2025, "unit": "万元",
            "header": rect(2, 4, 1, 10), "data": rect(5, 10, 1, 10),
            "dimensions": [dim(1, 5, 10, "大区"), dim(2, 5, 10, "门店名称")],
            "channel_aliases": {"网店": "线上", "门店": "线下"},
        },
        "checks": {"records": 32, "errors": 8, "mismatch": 8},
    },
    {
        "file": "03_flat_single_header.xlsx",
        "expect_commit": True,    # 差异不阻断
        "mapping": {
            "name": "e2e-单层复合", "sheet_name": "1月-6月",
            "report_year": 2025, "unit": "元",
            "header": rect(2, 2, 1, 6), "data": rect(3, 8, 1, 6),
            "dimensions": [dim(1, 3, 8, "区域"), dim(2, 3, 8, "门店")],
            "channel_aliases": {},
        },
        "checks": {"records": 16, "errors": 0, "mismatch": 1},
    },
    {
        "file": "04_formula_cache_modes.xlsx",
        "expect_commit": True,
        "mapping": {
            "name": "e2e-公式好表", "sheet_name": "有缓存值",
            "report_year": 2025, "unit": "元",
            "header": rect(1, 1, 1, 3), "data": rect(2, 4, 1, 3),
            "dimensions": [dim(1, 2, 4, "门店")],
            "channel_aliases": {},
        },
        "checks": {"records": 4, "errors": 0, "mismatch": 0},
    },
]


def main() -> int:
    failures = 0
    for case in CASES:
        wid = upload(SAMPLE / case["file"])
        status, preview = post_json("/api/mappings/preview-extract", {
            "workbook_id": wid, "mapping": case["mapping"],
        })
        s = preview["summary"]
        c = case["checks"]
        ok_preview = (
            s["record_count"] == c["records"]
            and s["error_count"] == c["errors"]
            and s["reconcile_mismatch_count"] == c["mismatch"]
        )
        commit_status, commit = post_json("/api/imports/commit", {
            "workbook_id": wid, "mapping": case["mapping"], "save_mapping": False,
        })
        if case["expect_commit"]:
            ok_commit = commit_status == 200
        else:
            ok_commit = commit_status == 422
        line = (
            f"{'PASS' if ok_preview and ok_commit else 'FAIL'}  {case['file']}\n"
            f"      试展开: 记录={s['record_count']}(期望{c['records']}) "
            f"阻断={s['error_count']}(期望{c['errors']}) "
            f"差异={s['reconcile_mismatch_count']}(期望{c['mismatch']})\n"
            f"      入仓: HTTP {commit_status}"
            f"{'（期望 ' + ('200' if case['expect_commit'] else '422') + '）'}"
        )
        print(line)
        if not (ok_preview and ok_commit):
            failures += 1
    print(f"\n{'全部通过' if failures == 0 else f'{failures} 个用例失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
