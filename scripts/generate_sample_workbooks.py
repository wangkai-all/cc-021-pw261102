"""生成 4 份结构不同的门店销售月报示例工作簿。

运行：.venv/bin/python -I scripts/generate_sample_workbooks.py
输出：sample_workbooks/
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parents[1] / "sample_workbooks"
OUT.mkdir(parents=True, exist_ok=True)

BOLD = Font(bold=True)
CENTER = Alignment(horizontal="center", vertical="center")
FILL = PatternFill("solid", fgColor="D9E1F2")


def _style_header(ws, cells) -> None:
    for ref in cells:
        c = ws[ref]
        c.font = BOLD
        c.alignment = CENTER
        c.fill = FILL


# ---------------------------------------------------------------------------
# 1. 标准双层表头：月份(合并) x 线上/线下，区域+门店维度，含小计/合计，单位：元
# ---------------------------------------------------------------------------
def build_standard() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "门店销售月报"
    # 行1: 标题
    ws["A1"] = "2025年门店销售月报（单位：元）"
    ws.merge_cells("A1:F1")
    ws["A1"].font = Font(bold=True, size=14)

    # 行2-3 双层表头
    ws["A2"] = "区域"; ws.merge_cells("A2:A3")
    ws["B2"] = "门店"; ws.merge_cells("B2:B3")
    ws["C2"] = "1月"; ws.merge_cells("C2:D2")
    ws["C3"] = "线上"; ws["D3"] = "线下"
    ws["E2"] = "2月"; ws.merge_cells("E2:F2")
    ws["E3"] = "线上"; ws["F3"] = "线下"
    _style_header(ws, ["A2", "B2", "C2", "D2", "E2", "F2", "C3", "D3", "E3", "F3"])

    rows = [
        # 区域, 门店, 1月线上, 1月线下, 2月线上, 2月线下
        # None=空白缺失，"—"=显式缺失标记，二者都不参与合计
        ("华东", "上海南京西路店", 120000, 340000, 132000, None),
        (None,   "杭州湖滨店",      88000, 210000, "—", 205000),
        (None,   "小计",            None, None, None, None),  # 静态合计行
        ("华北", "北京国贸店",      156000, 420000, 160000, 418000),
        (None,   "天津滨江道店",    64000, 175000, 70000, 172000),
        (None,   "小计",            None, None, None, None),
        (None,   "合计",            None, None, None, None),
        (None,   "备注：线下含团购订单", None, None, None, None),
    ]
    start = 4
    for i, (region, store, *vals) in enumerate(rows):
        r = start + i
        ws.cell(r, 1, region)
        ws.cell(r, 2, store)
        for j, v in enumerate(vals):
            if v is not None:
                ws.cell(r, 3 + j, v)

    # 区域纵向合并
    ws.merge_cells("A4:A5")   # 华东
    ws.merge_cells("A7:A8")   # 华北
    # 小计/合计为静态数值（等价于带缓存的公式结果）。
    # 空白与“—”是缺失值，不参与求和；无缓存公式的阻断场景由 02、04 号演示。
    def num(v):
        return v if isinstance(v, (int, float)) else 0

    subtotal_1 = [sum(num(r[2 + k]) for r in rows[:2]) for k in range(4)]
    subtotal_2 = [sum(num(r[2 + k]) for r in rows[3:5]) for k in range(4)]
    for j, v in enumerate(subtotal_1):
        ws.cell(6, 3 + j, v)
    for j, v in enumerate(subtotal_2):
        ws.cell(9, 3 + j, v)
    for j in range(4):
        ws.cell(10, 3 + j, subtotal_1[j] + subtotal_2[j])

    for col, w in zip("ABCDEF", (10, 20, 12, 12, 12, 12)):
        ws.column_dimensions[col].width = w
    wb.save(OUT / "01_standard_dual_header.xlsx")


# ---------------------------------------------------------------------------
# 2. 万元单位 + 三层表头（季度/月份/渠道），渠道命名不同（网店/门店）
# ---------------------------------------------------------------------------
def build_wanyuan_three_level() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "销售月报"
    ws["A1"] = "2025年度销售月报（单位：万元）"
    ws.merge_cells("A1:H1")
    ws["A1"].font = Font(bold=True, size=14)

    ws["A2"] = "大区"; ws.merge_cells("A2:A4")
    ws["B2"] = "门店名称"; ws.merge_cells("B2:B4")
    # Q1 合并 4 列
    ws["C2"] = "一季度"; ws.merge_cells("C2:F2")
    ws["G2"] = "二季度"; ws.merge_cells("G2:J2")
    # 月份各合并 2 列
    ws["C3"] = "1月"; ws.merge_cells("C3:D3")
    ws["E3"] = "2月"; ws.merge_cells("E3:F3")
    ws["G3"] = "4月"; ws.merge_cells("G3:H3")
    ws["I3"] = "5月"; ws.merge_cells("I3:J3")
    channels = ["网店", "门店"]
    for idx, base in enumerate([3, 5, 7, 9]):
        ws.cell(4, base, channels[0])
        ws.cell(4, base + 1, channels[1])
    _style_header(ws, [f"{c}2" for c in "AB"] +
                  [f"{get_column_letter(c)}3" for c in range(3, 11)] +
                  [f"{get_column_letter(c)}4" for c in range(3, 11)])

    data = [
        ("华南", "广州天河城店", 12.5, 33.8, 13.1, 34.2, 14.0, 35.1, 14.6, 36.0),
        (None,   "深圳福田店",   18.2, 41.5, 17.9, 42.0, 19.0, 43.3, 19.4, 44.1),
        ("西南", "成都春熙路店", 9.8, 26.4, 10.2, 27.0, 10.9, 27.6, 11.1, 28.2),
        (None,   "重庆解放碑店", 7.6, 20.1, 7.9, 20.5, 8.3, 21.0, 8.5, 21.4),
    ]
    for i, row in enumerate(data):
        r = 5 + i
        for j, v in enumerate(row):
            if v is not None:
                ws.cell(r, j + 1, v)
    ws.merge_cells("A5:A6")
    ws.merge_cells("A7:A8")

    # 合计行（数值，静态）
    total_row = 9
    ws.cell(total_row, 1, "全渠道合计")
    ws.merge_cells(f"A{total_row}:B{total_row}")
    for c in range(3, 11):
        col = get_column_letter(c)
        ws.cell(total_row, c, f"=SUM({col}5:{col}8)")

    # 备注行
    ws.cell(10, 1, "注：网店为自营小程序与第三方平台合计")
    ws.merge_cells("A10:J10")

    for c in range(1, 11):
        ws.column_dimensions[get_column_letter(c)].width = 13
    wb.save(OUT / "02_wanyuan_three_level.xlsx")


# ---------------------------------------------------------------------------
# 3. 单层表头（月份和渠道写在一个单元格：1月-线上），含“—”和空白
# ---------------------------------------------------------------------------
def build_flat_header() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "1月-6月"
    ws["A1"] = "门店销售月报 2025（元）"
    ws.merge_cells("A1:F1")
    ws["A1"].font = Font(bold=True, size=14)

    headers = ["区域", "门店", "3月-线上", "3月-线下", "6月-线上", "6月-线下"]
    for c, h in enumerate(headers, 1):
        ws.cell(2, c, h)
    _style_header(ws, [f"{get_column_letter(c)}2" for c in range(1, 7)])

    rows = [
        ("华中", "武汉光谷店", 95000, 260000, "—", 271000),
        (None,   "长沙五一广场店", 72000, 198000, 78000, None),
        ("西北", "西安钟楼店", 61000, 173000, 65000, 178000),
        (None,   "兰州城关店", 38000, 99000, 41000, 102000),
        (None,   "区域合计", None, None, None, None),
    ]
    for i, row in enumerate(rows):
        r = 3 + i
        for j, v in enumerate(row):
            if v is not None:
                ws.cell(r, j + 1, v)
    ws.merge_cells("A3:A4")
    ws.merge_cells("A5:A6")
    # 合计为原表口径静态值；其中 3月线下含一笔团购调整 12000，
    # 展开明细侧没有对应门店行，核对时应能定位到该合计单元格
    totals = [95000 + 72000 + 61000 + 38000,
              260000 + 198000 + 173000 + 99000 + 12000,
              78000 + 65000 + 41000,
              271000 + 178000 + 102000]
    for j, t in enumerate(totals):
        ws.cell(7, 3 + j, t)

    ws.cell(8, 1, "备注：3月线下合计含团购调整12000元；3月线上兰州店数据待财务确认")
    ws.merge_cells("A8:F8")
    for c in range(1, 7):
        ws.column_dimensions[get_column_letter(c)].width = 15
    wb.save(OUT / "03_flat_single_header.xlsx")


# ---------------------------------------------------------------------------
# 4. 含无缓存公式的工作簿（模拟 WPS/其他工具导出，data_only 读不到值）
#    openpyxl 无法写缓存值，因此直接构造 xlsx 内部 XML：
#    用一份带公式 + 缓存值的“好表”和一份只有公式的“坏表”两个 sheet。
# ---------------------------------------------------------------------------
def build_formula_modes() -> None:
    wb = Workbook()
    # 好表：直接写数值作为“缓存已存在”的对照
    ws_ok = wb.active
    ws_ok.title = "有缓存值"
    ws_ok["A1"] = "门店"; ws_ok["B1"] = "1月线上"; ws_ok["C1"] = "1月线下"
    _style_header(ws_ok, ["A1", "B1", "C1"])
    ws_ok.append(["南京新街口店", 210000, 330000])
    ws_ok.append(["苏州观前街店", 150000, 260000])
    ws_ok.append(["合计", 360000, 590000])  # 静态值，相当于公式缓存

    # 坏表：公式无缓存（openpyxl 写出的公式在 data_only=True 下即为 None）
    ws_bad = wb.create_sheet("无缓存公式")
    ws_bad["A1"] = "门店"; ws_bad["B1"] = "1月线上"; ws_bad["C1"] = "1月线下"
    _style_header(ws_bad, ["A1", "B1", "C1"])
    ws_bad.append(["南京新街口店", 210000, 330000])
    ws_bad.append(["苏州观前街店", 150000, 260000])
    ws_bad["A4"] = "合计"
    ws_bad["B4"] = "=B2+B3"
    ws_bad["C4"] = "=C2+C3"

    for ws in (ws_ok, ws_bad):
        ws.column_dimensions["A"].width = 18
        ws.column_dimensions["B"].width = 12
        ws.column_dimensions["C"].width = 12
    wb.save(OUT / "04_formula_cache_modes.xlsx")


def main() -> None:
    build_standard()
    build_wanyuan_three_level()
    build_flat_header()
    build_formula_modes()
    for p in sorted(OUT.glob("*.xlsx")):
        print(f"generated: {p.relative_to(OUT.parents[0])} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
