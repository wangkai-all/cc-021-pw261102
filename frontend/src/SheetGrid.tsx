import { useRef, useState } from 'react'
import type { PreviewCell, Rect, SheetPreview } from './types'

export type SelectMode = 'header' | 'data' | 'dim'

interface Props {
  preview: SheetPreview
  headerRect: Rect | null
  dataRect: Rect | null
  dimCols: number[]
  highlightCoord: string | null
  mode: SelectMode
  onHeaderRect: (r: Rect) => void
  onDataRect: (r: Rect) => void
  onToggleDim: (col: number) => void
}

const MODES: { key: SelectMode; label: string }[] = [
  { key: 'header', label: '框选表头区域' },
  { key: 'data', label: '框选数据区域' },
  { key: 'dim', label: '点选维度列（再点取消）' },
]

function inRect(r: number, c: number, rect: Rect | null) {
  return !!rect && r >= rect.row_start && r <= rect.row_end
    && c >= rect.col_start && c <= rect.col_end
}

function cellText(cell: PreviewCell | undefined): { text: string; cls: string } {
  if (!cell || cell.v === null || cell.v === '') {
    if (cell?.f && !cell.hc) return { text: '∅ 公式无缓存', cls: 'no-cache' }
    return { text: cell?.v === '' ? '' : '', cls: 'missing' }
  }
  if (cell.f) {
    return { text: String(cell.v), cls: cell.hc ? 'formula' : 'no-cache' }
  }
  if (cell.v === '—' || cell.v === '-') return { text: String(cell.v), cls: 'missing' }
  return { text: String(cell.v), cls: '' }
}

export default function SheetGrid({
  preview, headerRect, dataRect, dimCols, highlightCoord, mode,
  onHeaderRect, onDataRect, onToggleDim,
}: Props) {
  const [dragStart, setDragStart] = useState<[number, number] | null>(null)
  const [dragNow, setDragNow] = useState<[number, number] | null>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const cellRefs = useRef<Map<string, HTMLTableCellElement>>(new Map())

  const dragRect: Rect | null = dragStart && dragNow
    ? {
        row_start: Math.min(dragStart[0], dragNow[0]),
        row_end: Math.max(dragStart[0], dragNow[0]),
        col_start: Math.min(dragStart[1], dragNow[1]),
        col_end: Math.max(dragStart[1], dragNow[1]),
      }
    : null

  function startDrag(r: number, c: number) {
    if (mode === 'dim') {
      onToggleDim(c)
      return
    }
    setDragStart([r, c])
    setDragNow([r, c])
  }

  function moveDrag(r: number, c: number) {
    if (dragStart) setDragNow([r, c])
  }

  function endDrag() {
    if (dragRect) {
      if (mode === 'header') onHeaderRect(dragRect)
      else if (mode === 'data') onDataRect(dragRect)
    }
    setDragStart(null)
    setDragNow(null)
  }

  const activeRect = mode === 'header' ? headerRect : mode === 'data' ? dataRect : null

  return (
    <div>
      <div className="mode-bar">
        {MODES.map((m) => (
          <span key={m.key} className={`mode-pill ${mode === m.key ? 'on' : ''}`}>
            {m.label}
          </span>
        ))}
        <span className="hint" style={{ margin: 0 }}>
          共 {preview.max_row} 行 × {preview.max_col} 列，当前展示 {preview.shown_rows} × {preview.shown_cols}
        </span>
      </div>
      <div className="legend">
        <span className="lg-header">表头区域</span>
        <span className="lg-data">数据区域</span>
        <span className="lg-dim">维度列</span>
        <span className="lg-formula">公式（有缓存）</span>
        <span className="lg-nocache">公式无缓存 / 阻断</span>
      </div>
      <div className="grid-wrap" ref={gridRef}>
        <table className="sheet" onMouseUp={endDrag} onMouseLeave={endDrag}>
          <thead>
            <tr>
              <th className="rowhead">#</th>
              {preview.col_letters.map((letter, i) => (
                <th key={letter}>{letter}<br />
                  <span style={{ fontWeight: 400, color: '#9ca3af' }}>{i + 1}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((rowCells, ri) => {
              const r = ri + 1
              return (
                <tr key={r}>
                  <td className="rowhead">{r}</td>
                  {rowCells.map((cell, ci) => {
                    const c = ci + 1
                    const { text, cls } = cellText(cell)
                    const isHeader = inRect(r, c, headerRect)
                    const isData = inRect(r, c, dataRect)
                    const isDim = dimCols.includes(c)
                    const isDrag = inRect(r, c, dragRect)
                    const coord = `${preview.sheet}!${preview.col_letters[ci]}${r}`
                    const isHighlight = highlightCoord === coord
                    const mergeAnchor = preview.merges.some(
                      (m) => m.min_row === r && m.min_col === c,
                    )
                    return (
                      <td
                        key={c}
                        ref={(el) => {
                          if (el) cellRefs.current.set(coord, el)
                          else cellRefs.current.delete(coord)
                        }}
                        title={cell.f ? `公式: ${cell.raw}${cell.hc ? '（有缓存值）' : '（无缓存值，阻断）'}` : coord}
                        className={[
                          'cell',
                          cls,
                          isHeader ? 'in-header' : '',
                          isData ? 'in-data' : '',
                          isDim ? 'in-dim' : '',
                          isDrag ? 'selecting' : '',
                          mergeAnchor ? 'merge-anchor' : '',
                          isHighlight ? 'selecting' : '',
                        ].join(' ')}
                        style={isHighlight ? { outline: '3px solid #b91c1c' } : undefined}
                        onMouseDown={() => startDrag(r, c)}
                        onMouseEnter={() => moveDrag(r, c)}
                      >
                        {text}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {activeRect && (
        <p className="hint">
          已选{mode === 'header' ? '表头' : '数据'}区域：
          <span className="mono">
            行 {activeRect.row_start}–{activeRect.row_end}，列 {activeRect.col_start}–{activeRect.col_end}
          </span>
        </p>
      )}
    </div>
  )
}
