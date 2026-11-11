# 门店销售月报 · 展开入仓工作台

把带**合并表头、横向铺开的月份、穿插合计行**的门店销售月报，拆成可直接分析的明细表，
并落地到 DuckDB。流程：**导入 xlsx → 预览原表 → 选择表头/维度/数据区域与单位 → 确认展开结果 → 入仓**。

## 技术栈

| 层 | 技术 | 职责 |
| --- | --- | --- |
| 读取 | openpyxl | 工作簿双视图（公式视图 + 缓存值视图）、合并区域、坐标 |
| 引擎 | 纯 Python | 受限合并填充、多层表头解析、月份/渠道展开、单位换算、缺失处理、合计核对 |
| 存储 | DuckDB | 明细表、导入批次、问题清单、核对结果、可复用映射（含结构指纹） |
| 接口 | FastAPI | 上传、预览、试展开、复用校验、确认入仓、查询 |
| 前端 | React + TypeScript + Vite | 框选区域、点选维度、问题/核对/明细三页确认、坐标点回原表 |

## 目录结构

```
backend/
  app/
    grid.py        # openpyxl 双视图网格，公式 is_formula / has_cached_value
    ranges.py      # A1 区域解析 + 仅在表头/维度范围内的合并填充
    models.py      # 映射模型、月份/金额/缺失/合计关键字解析
    extractor.py   # 展开引擎、问题收集、合计核对、结构指纹
    storage.py     # DuckDB 建表与入仓
    api.py         # FastAPI 路由（生产环境同时托管前端 dist）
  tests/           # pytest：10 个用例覆盖 4 份示例工作簿
scripts/
  generate_sample_workbooks.py   # 生成 4 份结构不同的示例月报
sample_workbooks/                # 生成产物（已附带）
frontend/
  src/
    SheetGrid.tsx    # 可框选的原表网格，公式/缺失/合并高亮
    ResultTabs.tsx   # 合计核对 / 展开明细 / 问题清单
    App.tsx          # 四步流程编排
data/
  uploads/           # 上传的工作簿（运行时）
  duckdb/            # report.duckdb（运行时）
```

## 快速开始

```bash
# 1. Python 虚拟环境与依赖
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. 生成 4 份示例工作簿（仓库已附带，可重新生成）
.venv/bin/python -I scripts/generate_sample_workbooks.py

# 3. 后端测试
.venv/bin/python -I -m pytest backend/tests/ -v

# 4. 启动后端（http://127.0.0.1:8000）
.venv/bin/python -I -m uvicorn app.api:app --app-dir backend --port 8000

# 5. 前端（另开终端，http://localhost:5173，/api 代理到 8000）
cd frontend
npm install
npm run dev
```

生产模式：`npm run build` 后，FastAPI 会自动挂载 `frontend/dist`，只暴露 8000 一个端口。

## 4 份示例工作簿（结构各不相同）

| 文件 | 结构特点 | 覆盖的规则 |
| --- | --- | --- |
| `01_standard_dual_header.xlsx` | 月份横向合并 + 线上/线下双层表头，区域纵向合并，小计/合计/备注，空白与“—” | 标准展开、维度补齐、缺失保留、小计与总计核对 |
| `02_wanyuan_three_level.xlsx` | 季度/月份/渠道三层表头，单位**万元**，渠道叫“网店/门店”，合计是**无缓存公式** | 三层表头、万元换算、渠道别名、无缓存公式 422 阻断 |
| `03_flat_single_header.xlsx` | 单层复合表头 `3月-线上`，合计含一笔团购调整 12000 | 复合表头拆月份+渠道、差异精确定位到合计单元格 |
| `04_formula_cache_modes.xlsx` | 两个 sheet：静态值（等价有缓存）vs 无缓存公式 | 公式缓存读取与标记、无缓存阻断且不拿公式文本当金额 |

## 核心业务规则（与需求逐条对应）

1. **受限的合并填充**：合并值只补到“选定的表头区域”和“选定的维度列”；
   数据区域绝不填充，空白保持空白。表头横并（月份）与维度列纵并（区域）分别处理。
2. **合计/小计/备注跳过**：行内任一维度文本命中 `合计/小计/总计/备注/注/说明` 即跳过展开，
   但合计行会单独保留用于核对，备注行登记为 info 问题。
3. **缺失保留**：空白与 `— / – / － / / / N/A / 无` 统一落为 `amount_yuan = NULL`、
   `value_source = 'missing'`，不填 0。
4. **单位换算**：`元 ×1`、`万元 ×10000`，换算后统一存元，原单位留痕在 `unit` 列。
5. **月份转换**：结合配置的报表年份，把 `1月 / 2025年3月 / 3` 等转成 `YYYY-MM`；
   拿不准的单元格生成 error 级问题并列出坐标，不猜测。
6. **公式安全**：
   - 有缓存值 → 读缓存，`value_source='formula_cache'`；
   - 无缓存值 → error 阻断，保留公式文本在问题里供人工判断，**绝不把公式字符串当金额**；
   - 存在阻断问题时 `/api/imports/commit` 返回 422，拒绝入仓。
7. **完整溯源**：每条明细带 `workbook_name / sheet_name / cell_row / cell_col /
   cell_coordinate（如 门店销售月报!C4）/ value_source / formula_text`，界面点坐标即高亮原表单元格。
8. **映射复用与结构指纹**：映射可保存。复用前比对表头区域填充后文本的 SHA-256 指纹；
   指纹不一致（表头结构变化）时前端停在预览确认页并提示新旧指纹，不允许直接确认。
9. **合计核对**：原表合计 vs 展开明细按「月份 × 渠道」比对；
   小计只比其辖区内明细，总计比全量；容差 0.01 元。每项差异带来源坐标，可直接定位。

## DuckDB 表

- `fact_store_sales`：展开后的明细事实表（含全量溯源字段）
- `import_batch`：每次导入的批次与统计
- `import_issue`：阻断/警告/提示问题，带坐标
- `reconciliation`：合计核对结果与差异
- `mapping_config`：可复用映射及其结构指纹

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/workbooks/upload` | 上传 xlsx，返回工作表清单 |
| GET | `/api/workbooks/{id}/sheets/{sheet}/preview` | 网格预览（值/公式/缓存/合并） |
| POST | `/api/mappings/preview-extract` | 试展开，不写库 |
| POST | `/api/mappings/reuse-check` | 复用映射的指纹比对 |
| GET | `/api/mappings` | 已保存映射 |
| POST | `/api/imports/commit` | 确认入仓（有阻断问题返回 422） |
| GET | `/api/imports` / `/api/imports/{id}/facts` | 批次与全量明细/问题/核对 |

## 设计取舍

- openpyxl 同文件开两次（`data_only=False/True`），分别拿公式文本与缓存值，
  避免二者互相覆盖；无缓存公式格在网格层保留为 `value=None` 而非丢弃。
- 核对作用域按**单元格行号窗口**界定小计范围，不依赖可变缓冲，顺序无关、可重放。
- 指纹只含表头文本结构与维度定义，不含报表年份——年份属于期次参数而非结构。
