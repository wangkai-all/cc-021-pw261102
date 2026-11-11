"""FastAPI 接口：上传、预览、试展开、确认入仓、映射复用与核对查询。"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .extractor import extract
from .grid import load_workbook_grid
from .models import (
    DataSelection,
    HeaderSelection,
    MappingConfig,
    MappingPayload,
)
from .ranges import to_a1
from .storage import Storage

UPLOAD_DIR = Path(
    os.environ.get("REPORT_UPLOAD_DIR",
                   Path(__file__).resolve().parents[2] / "data" / "uploads")
)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="门店销售月报展开入仓", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 会话级缓存：workbook_id -> 磁盘路径（进程内；重启后凭路径可重新打开）
_WORKBOOKS: dict[str, str] = {}


def _storage() -> Storage:
    return Storage()


def _resolve_workbook(workbook_id: str) -> str:
    path = _WORKBOOKS.get(workbook_id)
    if path and Path(path).exists():
        return path
    # 兼容进程重启：workbook_id 即上传时的文件名
    candidate = UPLOAD_DIR / workbook_id
    if candidate.exists():
        return str(candidate)
    raise HTTPException(404, f"工作簿不存在或已被清理: {workbook_id}")


def _build_config(payload: MappingPayload, fingerprint: str = "") -> MappingConfig:
    return MappingConfig(
        name=payload.name,
        sheet_name=payload.sheet_name,
        report_year=payload.report_year,
        unit=payload.unit,
        header=HeaderSelection(**payload.header.model_dump()),
        data=DataSelection(**payload.data.model_dump()),
        dimensions=[d.model_dump() for d in payload.dimensions],
        channel_aliases=dict(payload.channel_aliases),
        fingerprint=fingerprint,
    )


# ---------------- 上传与预览 ----------------

@app.post("/api/workbooks/upload")
def upload_workbook(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "仅支持 .xlsx / .xlsm 工作簿")
    workbook_id = f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    dest = UPLOAD_DIR / workbook_id
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    _WORKBOOKS[workbook_id] = str(dest)
    wb = load_workbook_grid(str(dest))
    return {
        "workbook_id": workbook_id,
        "original_name": file.filename,
        "sheets": [
            {
                "name": g.name,
                "max_row": g.max_row,
                "max_col": g.max_col,
                "merge_count": len(g.merges),
            }
            for g in wb.sheets.values()
        ],
    }


@app.get("/api/workbooks/{workbook_id}/sheets/{sheet_name}/preview")
def preview_sheet(
    workbook_id: str, sheet_name: str,
    max_rows: int = 60, max_cols: int = 30,
) -> dict[str, Any]:
    path = _resolve_workbook(workbook_id)
    wb = load_workbook_grid(path)
    if sheet_name not in wb.sheets:
        raise HTTPException(404, f"工作表不存在: {sheet_name}")
    grid = wb.sheets[sheet_name]
    mr = min(grid.max_row, max_rows)
    mc = min(grid.max_col, max_cols)

    rows: list[list[dict[str, Any]]] = []
    for r in range(1, mr + 1):
        row: list[dict[str, Any]] = []
        for c in range(1, mc + 1):
            info = grid.get(r, c)
            if info is None:
                row.append({"v": None, "f": False, "hc": False})
            else:
                row.append({
                    "v": info.value,
                    "f": info.is_formula,
                    "hc": info.has_cached_value,
                    "raw": info.raw if info.is_formula else None,
                })
        rows.append(row)

    return {
        "sheet": sheet_name,
        "max_row": grid.max_row,
        "max_col": grid.max_col,
        "shown_rows": mr,
        "shown_cols": mc,
        "col_letters": [to_a1(1, c)[:-1] for c in range(1, mc + 1)],
        "rows": rows,
        "merges": [
            {
                "min_row": m.min_row, "max_row": m.max_row,
                "min_col": m.min_col, "max_col": m.max_col,
                "anchor_value": grid.merge_topleft.get(
                    (m.min_row, m.max_row, m.min_col, m.max_col)
                ),
            }
            for m in grid.merges
            if m.min_row <= mr and m.min_col <= mc
        ],
    }


# ---------------- 试展开（不写库） ----------------

class PreviewExtractBody(BaseModel):
    workbook_id: str
    mapping: MappingPayload
    persist_mapping: bool = False


@app.post("/api/mappings/preview-extract")
def preview_extract(body: PreviewExtractBody) -> dict[str, Any]:
    path = _resolve_workbook(body.workbook_id)
    wb = load_workbook_grid(path)
    cfg = _build_config(body.mapping)
    result = extract(wb, cfg)

    if body.persist_mapping:
        with _storage() as st:
            st.save_mapping(cfg.to_dict(), result.fingerprint)

    return {
        "fingerprint": result.fingerprint,
        "summary": result.summary(),
        "header_columns": [
            {
                "col": h.col, "path": h.path, "month": h.month,
                "month_display": h.month_display,
                "channel": h.channel, "channel_raw": h.channel_raw,
                "coordinate": f"{cfg.sheet_name}!{to_a1(cfg.header.row_start, h.col)}",
            }
            for h in result.header_columns
        ],
        "total_rows": [
            {
                "row": t.row, "label": t.label, "kind": t.kind,
                "coordinates": t.coordinates,
                "values": {str(k): v for k, v in t.values.items()},
            }
            for t in result.total_rows
        ],
        "records": [r.to_dict() for r in result.records[:200]],
        "record_truncated": len(result.records) > 200,
        "issues": [i.to_dict() for i in result.issues],
        "reconciliation": [r.to_dict() for r in result.reconciliation],
    }


# ---------------- 映射复用与结构指纹 ----------------

class ReuseBody(BaseModel):
    workbook_id: str
    mapping_name: str
    sheet_name: str | None = None


@app.post("/api/mappings/reuse-check")
def reuse_check(body: ReuseBody) -> dict[str, Any]:
    """复用映射前比对结构指纹；不一致则要求停在预览确认。"""
    with _storage() as st:
        saved = st.get_mapping(body.mapping_name)
    if saved is None:
        raise HTTPException(404, f"映射不存在: {body.mapping_name}")
    path = _resolve_workbook(body.workbook_id)
    wb = load_workbook_grid(path)
    cfg_dict = saved["config"]
    if body.sheet_name:
        cfg_dict["sheet_name"] = body.sheet_name
    cfg = MappingConfig(
        name=cfg_dict["name"],
        sheet_name=cfg_dict["sheet_name"],
        report_year=cfg_dict["report_year"],
        unit=cfg_dict["unit"],
        header=HeaderSelection(**cfg_dict["header"]),
        data=DataSelection(**cfg_dict["data"]),
        dimensions=cfg_dict["dimensions"],
        channel_aliases=cfg_dict.get("channel_aliases", {}),
    )
    result = extract(wb, cfg)
    matches = result.fingerprint == saved["fingerprint"]
    return {
        "structure_matches": matches,
        "saved_fingerprint": saved["fingerprint"],
        "current_fingerprint": result.fingerprint,
        "mapping": cfg_dict,
        # 无论是否匹配都回传试展开结果，供前端停在预览确认页人工核对
        "preview": {
            "summary": result.summary(),
            "header_columns": [
                {"col": h.col, "path": h.path, "month": h.month,
                 "channel": h.channel, "channel_raw": h.channel_raw}
                for h in result.header_columns
            ],
            "issues": [i.to_dict() for i in result.issues],
            "reconciliation": [r.to_dict() for r in result.reconciliation],
        },
    }


@app.get("/api/mappings")
def list_mappings() -> dict[str, Any]:
    with _storage() as st:
        return {"mappings": st.list_mappings()}


# ---------------- 确认入仓 ----------------

class CommitBody(BaseModel):
    workbook_id: str
    mapping: MappingPayload
    mapping_name: str | None = None
    save_mapping: bool = True


@app.post("/api/imports/commit")
def commit_import(body: CommitBody) -> dict[str, Any]:
    path = _resolve_workbook(body.workbook_id)
    wb = load_workbook_grid(path)
    cfg = _build_config(body.mapping)
    result = extract(wb, cfg)

    # 有 error 级问题时拒绝入仓，引导先处理
    blocking = [i for i in result.issues if i.severity == "error"]
    if blocking:
        raise HTTPException(
            422,
            {
                "message": "存在阻断性问题，无法入仓，请先处理下列单元格",
                "issues": [i.to_dict() for i in blocking],
            },
        )

    import_id = uuid.uuid4().hex
    workbook_name = Path(path).name
    with _storage() as st:
        if body.save_mapping:
            st.save_mapping(cfg.to_dict(), result.fingerprint)
        summary = st.commit_import(
            import_id=import_id,
            workbook_path=path,
            workbook_name=workbook_name,
            mapping_name=body.mapping_name or body.mapping.name,
            cfg_dict=cfg.to_dict(),
            fingerprint=result.fingerprint,
            result=result,
        )
    return {
        "import_id": import_id,
        "workbook_name": workbook_name,
        "fingerprint": result.fingerprint,
        "summary": summary,
        "reconciliation": [r.to_dict() for r in result.reconciliation],
    }


@app.get("/api/imports")
def list_imports() -> dict[str, Any]:
    with _storage() as st:
        return {"imports": st.list_imports()}


@app.get("/api/imports/{import_id}/facts")
def get_facts(import_id: str, limit: int = 1000) -> dict[str, Any]:
    with _storage() as st:
        return {
            "facts": st.query_facts(import_id=import_id, limit=limit),
            "issues": st.get_issues(import_id),
            "reconciliation": st.get_reconciliation(import_id),
        }


# 生产环境由前端构建产物挂载（见 main.py 启动说明）
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
