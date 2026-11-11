import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError, commitImport, fetchFacts, fetchPreview, listImports, listMappings,
  previewExtract, reuseCheck, uploadWorkbook,
} from './api'
import ResultTabs from './ResultTabs'
import SheetGrid, { type SelectMode } from './SheetGrid'
import type {
  CommitResponse, MappingListItem, MappingSpec, PreviewExtractResponse,
  Rect, SheetPreview, UploadResponse,
} from './types'

type Step = 1 | 2 | 3 | 4

const EMPTY_MAPPING = (sheetName: string): MappingSpec => ({
  name: '',
  sheet_name: sheetName,
  report_year: new Date().getFullYear(),
  unit: '元',
  header: { row_start: 1, row_end: 1, col_start: 1, col_end: 1 },
  data: { row_start: 1, row_end: 1, col_start: 1, col_end: 1 },
  dimensions: [],
  channel_aliases: {},
})

export default function App() {
  const [step, setStep] = useState<Step>(1)
  const [upload, setUpload] = useState<UploadResponse | null>(null)
  const [sheet, setSheet] = useState('')
  const [preview, setPreview] = useState<SheetPreview | null>(null)
  const [mapping, setMapping] = useState<MappingSpec | null>(null)
  const [mode, setMode] = useState<SelectMode>('header')
  const [result, setResult] = useState<PreviewExtractResponse | null>(null)
  const [mappings, setMappings] = useState<MappingListItem[]>([])
  const [committed, setCommitted] = useState<CommitResponse | null>(null)
  const [imports, setImports] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warn, setWarn] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<string | null>(null)
  const [saveMapping, setSaveMapping] = useState(true)
  const fileInput = useRef<HTMLInputElement>(null)
  const gridTopRef = useRef<HTMLDivElement>(null)

  const loadMappings = useCallback(() => {
    listMappings().then((r) => setMappings(r.mappings)).catch(() => undefined)
  }, [])
  const loadImports = useCallback(() => {
    listImports().then((r) => setImports(r.imports)).catch(() => undefined)
  }, [])

  useEffect(() => {
    loadMappings()
    loadImports()
  }, [loadMappings, loadImports])

  // ---------------- 上传 ----------------
  async function handleFile(file: File) {
    setError(null)
    setBusy(true)
    try {
      const up = await uploadWorkbook(file)
      setUpload(up)
      const first = up.sheets[0]?.name ?? ''
      setSheet(first)
      setMapping(EMPTY_MAPPING(first))
      setResult(null)
      setCommitted(null)
      const pv = await fetchPreview(up.workbook_id, first)
      setPreview(pv)
      setStep(2)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  async function switchSheet(name: string) {
    if (!upload) return
    setSheet(name)
    setMapping((m) => (m ? { ...m, sheet_name: name, dimensions: [] } : m))
    setResult(null)
    setWarn(null)
    const pv = await fetchPreview(upload.workbook_id, name)
    setPreview(pv)
  }

  // ---------------- 选区回调 ----------------
  const dimCols = mapping?.dimensions.map((d) => d.col) ?? []

  function setHeaderRect(rect: Rect) {
    setMapping((m) => m && { ...m, header: rect })
  }
  function setDataRect(rect: Rect) {
    setMapping((m) => m && {
      ...m,
      data: rect,
      // 维度行范围默认跟随数据区域
      dimensions: m.dimensions.map((d) => ({ ...d, row_start: rect.row_start, row_end: rect.row_end })),
    })
  }
  function toggleDim(col: number) {
    setMapping((m) => {
      if (!m) return m
      const exists = m.dimensions.find((d) => d.col === col)
      if (exists) {
        return { ...m, dimensions: m.dimensions.filter((d) => d.col !== col) }
      }
      return {
        ...m,
        dimensions: [
          ...m.dimensions,
          {
            col,
            row_start: m.data.row_start,
            row_end: m.data.row_end,
            name: dimNameGuess(col, preview),
          },
        ],
      }
    })
  }

  function updateDimName(col: number, name: string) {
    setMapping((m) => m && {
      ...m,
      dimensions: m.dimensions.map((d) => (d.col === col ? { ...d, name } : d)),
    })
  }

  // ---------------- 试展开 ----------------
  async function runPreviewExtract() {
    if (!upload || !mapping) return
    setBusy(true)
    setError(null)
    try {
      const r = await previewExtract(upload.workbook_id, mapping, false)
      setResult(r)
      setStep(3)
      setWarn(null)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  // ---------------- 复用映射 ----------------
  async function applySavedMapping(name: string) {
    if (!upload) return
    setBusy(true)
    setError(null)
    setWarn(null)
    try {
      const r = await reuseCheck(upload.workbook_id, name)
      const cfg: MappingSpec = {
        ...r.mapping,
        name: r.mapping.name,
      }
      setMapping(cfg)
      setResult({
        fingerprint: r.current_fingerprint,
        summary: r.preview.summary,
        header_columns: r.preview.header_columns,
        total_rows: [],
        records: [],
        record_truncated: true,
        issues: r.preview.issues,
        reconciliation: r.preview.reconciliation,
      })
      const pv = await fetchPreview(upload.workbook_id, cfg.sheet_name)
      setSheet(cfg.sheet_name)
      setPreview(pv)
      if (r.structure_matches) {
        setWarn(`映射「${name}」结构指纹一致，可直接试展开后入仓。`)
        setStep(2)
      } else {
        // 表头结构变化：停在预览确认，不允许直接确认
        setWarn(`⚠ 表头结构已变化（指纹 ${r.saved_fingerprint} → ${r.current_fingerprint}），请重新核对选区后再试展开。`)
        setStep(2)
      }
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  // ---------------- 确认入仓 ----------------
  async function doCommit() {
    if (!upload || !mapping) return
    setBusy(true)
    setError(null)
    try {
      const r = await commitImport(upload.workbook_id, mapping, saveMapping)
      setCommitted(r)
      setStep(4)
      loadMappings()
      loadImports()
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError('入仓被阻断：存在无法读取的单元格，请回到“问题清单”按坐标处理后重试。')
      } else {
        setError(describe(e))
      }
    } finally {
      setBusy(false)
    }
  }

  function locate(coord: string) {
    setHighlight(coord)
    gridTopRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  async function viewImportFacts(importId: string) {
    const r = await fetchFacts(importId)
    setResult({
      fingerprint: '',
      summary: {
        record_count: r.facts.length, issue_count: r.issues.length,
        error_count: r.issues.filter((x: any) => x.severity === 'error').length,
        total_row_count: 0, reconcile_mismatch_count: r.reconciliation.filter((x: any) => !x.matched).length,
      },
      header_columns: [], total_rows: [],
      records: r.facts.map((f: any) => ({
        dimensions: JSON.parse(f.dimensions_json),
        month: f.report_month, channel: f.channel,
        amount_yuan: f.amount_yuan, unit: f.unit,
        value_source: f.value_source, workbook_path: f.workbook_path,
        sheet_name: f.sheet_name, coordinate: f.cell_coordinate,
        row: f.cell_row, col: f.cell_col, formula_text: f.formula_text,
      })),
      record_truncated: false,
      issues: r.issues, reconciliation: r.reconciliation,
    })
    setStep(3)
  }

  const canExtract = !!mapping && mapping.dimensions.length > 0
  const errorCount = result?.summary.error_count ?? 0
  const mismatchCount = result?.summary.reconcile_mismatch_count ?? 0

  return (
    <div className="app">
      <header className="app-header">
        <h1>门店销售月报 · 展开入仓工作台</h1>
        <p>合并表头拆平、合计行跳过、单位换算、公式缓存校验、明细可溯源到单元格</p>
      </header>

      <div className="steps">
        {(['上传工作簿', '预览与映射', '展开确认', '入仓结果'] as const).map((label, i) => (
          <span key={label} className={`step ${step === i + 1 ? 'active' : step > i + 1 ? 'done' : ''}`}>
            {i + 1}. {label}
          </span>
        ))}
      </div>

      {error && <div className="banner error">❌ {error}</div>}
      {warn && <div className="banner warn">{warn}</div>}

      {/* ---------------- Step 1 ---------------- */}
      {step === 1 && (
        <div className="card">
          <h2>① 选择 .xlsx 工作簿</h2>
          <div
            className="file-drop"
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('drag') }}
            onDragLeave={(e) => e.currentTarget.classList.remove('drag')}
            onDrop={(e) => {
              e.preventDefault()
              e.currentTarget.classList.remove('drag')
              const f = e.dataTransfer.files?.[0]
              if (f) handleFile(f)
            }}
          >
            <input
              ref={fileInput} type="file" accept=".xlsx,.xlsm" hidden
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
            <div style={{ fontSize: 15 }}>点击选择，或把工作簿拖到这里</div>
            <div className="hint">仅支持 xlsx / xlsm，文件保存在服务端 data/uploads</div>
          </div>

          {mappings.length > 0 && (
            <>
              <h3>已保存的映射（下一期可复用，结构变化时会停在预览确认）</h3>
              <table className="data">
                <thead><tr><th>映射名</th><th>工作表</th><th>年份</th><th>单位</th><th>指纹</th><th></th></tr></thead>
                <tbody>
                  {mappings.map((m) => (
                    <tr key={m.name}>
                      <td>{m.name}</td><td>{m.sheet_name}</td><td>{m.report_year}</td>
                      <td>{m.unit}</td><td className="mono">{m.fingerprint}</td>
                      <td>
                        <button disabled={!upload || busy} onClick={() => applySavedMapping(m.name)}>
                          先上传工作簿后可复用
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {imports.length > 0 && (
            <>
              <h3>已入仓批次</h3>
              <table className="data">
                <thead><tr><th>工作簿</th><th>明细数</th><th>阻断</th><th>核对差异</th><th>时间</th><th></th></tr></thead>
                <tbody>
                  {imports.map((b) => (
                    <tr key={b.import_id}>
                      <td>{b.workbook_name}</td>
                      <td className="num">{b.record_count}</td>
                      <td className="num">{b.error_count}</td>
                      <td className="num">{b.mismatch_count}</td>
                      <td>{b.imported_at?.replace('T', ' ').slice(0, 19)}</td>
                      <td><button onClick={() => viewImportFacts(b.import_id)}>查看明细/核对</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      {/* ---------------- Step 2/3 ---------------- */}
      {(step === 2 || step === 3) && upload && preview && mapping && (
        <>
          <div className="card" ref={gridTopRef}>
            <h2>② 预览原表并选择区域</h2>
            <div className="form-row" style={{ marginBottom: 12 }}>
              <div className="form-field">
                <label>工作表</label>
                <select value={sheet} onChange={(e) => switchSheet(e.target.value)} style={{ width: 220 }}>
                  {upload.sheets.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
                </select>
              </div>
              <div className="form-field">
                <label>报表年份（月份表头按此年转换）</label>
                <input type="number" value={mapping.report_year}
                  onChange={(e) => setMapping({ ...mapping, report_year: Number(e.target.value) })} />
              </div>
              <div className="form-field">
                <label>报表单位（自动换算为元）</label>
                <select value={mapping.unit}
                  onChange={(e) => setMapping({ ...mapping, unit: e.target.value })}>
                  <option value="元">元（×1）</option>
                  <option value="万元">万元（×10,000）</option>
                </select>
              </div>
              <div className="form-field">
                <label>映射名称（保存后可复用）</label>
                <input value={mapping.name} placeholder="如：2025门店月报标准映射"
                  onChange={(e) => setMapping({ ...mapping, name: e.target.value })} style={{ width: 240 }} />
              </div>
            </div>

            <div className="mode-bar">
              {(['header', 'data', 'dim'] as SelectMode[]).map((mm) => (
                <button key={mm} className={mode === mm ? 'primary' : ''}
                  onClick={() => setMode(mm)}>
                  {mm === 'header' ? '框选表头区域' : mm === 'data' ? '框选数据区域' : '点选维度列'}
                </button>
              ))}
            </div>

            <SheetGrid
              preview={preview}
              headerRect={mapping.header}
              dataRect={mapping.data}
              dimCols={dimCols}
              highlightCoord={highlight}
              mode={mode}
              onHeaderRect={setHeaderRect}
              onDataRect={setDataRect}
              onToggleDim={toggleDim}
            />

            {mapping.dimensions.length > 0 && (
              <>
                <h3>维度列命名</h3>
                <div className="chip-row">
                  {mapping.dimensions.map((d) => (
                    <span className="chip" key={d.col}>
                      第 {d.col} 列 →
                      <input
                        value={d.name}
                        onChange={(e) => updateDimName(d.col, e.target.value)}
                        style={{ width: 110, padding: '2px 6px' }}
                      />
                      <button onClick={() => toggleDim(d.col)} title="移除">✕</button>
                    </span>
                  ))}
                </div>
              </>
            )}

            <h3>渠道别名（可选，如 网店→线上）</h3>
            <ChannelAliases mapping={mapping} onChange={setMapping} />

            <div style={{ marginTop: 16, display: 'flex', gap: 10, alignItems: 'center' }}>
              <button className="primary" disabled={!canExtract || busy} onClick={runPreviewExtract}>
                {busy ? '处理中…' : '③ 试展开（不写库）'}
              </button>
              {!canExtract && <span className="hint">请先框选表头、数据区域并至少点选一个维度列</span>}
              {mappings.length > 0 && (
                <select value="" onChange={(e) => e.target.value && applySavedMapping(e.target.value)}
                  style={{ width: 260 }}>
                  <option value="">复用已保存映射…</option>
                  {mappings.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
                </select>
              )}
            </div>
          </div>

          {result && (
            <div className="card">
              <h2>③ 展开结果确认</h2>
              <div className="summary-tiles">
                <div className="tile good"><div className="n">{result.summary.record_count}</div><div className="l">明细记录</div></div>
                <div className={`tile ${errorCount ? 'bad' : 'good'}`}><div className="n">{errorCount}</div><div className="l">阻断问题</div></div>
                <div className="tile"><div className="n">{result.summary.issue_count}</div><div className="l">全部问题</div></div>
                <div className={`tile ${mismatchCount ? 'bad' : 'good'}`}><div className="n">{mismatchCount}</div><div className="l">合计核对差异</div></div>
                <div className="tile"><div className="n mono" style={{ fontSize: 14 }}>{result.fingerprint}</div><div className="l">结构指纹</div></div>
              </div>

              {result.header_columns.length > 0 && (
                <>
                  <h3>表头解析结果（月份 × 渠道）</h3>
                  <div className="chip-row">
                    {result.header_columns.map((h) => (
                      <span className="chip" key={h.col}>
                        列{h.col}：{h.month} · {h.channel}
                        {h.channel_raw && h.channel_raw !== h.channel && `（原:${h.channel_raw}）`}
                      </span>
                    ))}
                  </div>
                </>
              )}

              <ResultTabs
                issues={result.issues}
                reconciliation={result.reconciliation}
                records={result.records}
                onLocate={locate}
              />
              {result.record_truncated && <p className="hint">明细表仅预览前 200 条，入仓后为全量。</p>}

              <div style={{ marginTop: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
                <label className="form-field inline">
                  <input type="checkbox" checked={saveMapping}
                    onChange={(e) => setSaveMapping(e.target.checked)} />
                  保存/更新映射供下一期复用
                </label>
                <button className="primary" disabled={busy || errorCount > 0} onClick={doCommit}>
                  {errorCount > 0 ? '存在阻断问题，不能入仓' : '④ 确认入仓（DuckDB）'}
                </button>
                {mismatchCount > 0 && (
                  <span className="hint">合计核对有 {mismatchCount} 项差异，仍可入仓（明细与差异坐标均已留存）。</span>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* ---------------- Step 4 ---------------- */}
      {step === 4 && committed && (
        <div className="card">
          <h2>④ 入仓完成</h2>
          <div className="banner ok">
            ✅ 批次 {committed.import_id} 已写入 DuckDB，共 {committed.summary.record_count} 条明细，
            每条均带工作簿/工作表/单元格坐标，可在下方核对表点坐标回溯源。
          </div>
          <div className="summary-tiles">
            <div className="tile good"><div className="n">{committed.summary.record_count}</div><div className="l">入仓明细</div></div>
            <div className={`tile ${committed.summary.reconcile_mismatch_count ? 'bad' : 'good'}`}>
              <div className="n">{committed.summary.reconcile_mismatch_count}</div><div className="l">核对差异</div>
            </div>
            <div className="tile"><div className="n mono" style={{ fontSize: 14 }}>{committed.fingerprint}</div><div className="l">映射指纹</div></div>
          </div>
          {committed.reconciliation.length > 0 && (
            <ResultTabs issues={[]} reconciliation={committed.reconciliation} records={[]} onLocate={locate} />
          )}
          <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
            <button onClick={() => { setStep(1); setUpload(null); setResult(null); setCommitted(null); }}>
              导入下一份工作簿
            </button>
            <button onClick={() => viewImportFacts(committed.import_id)}>查看本批次全量明细</button>
          </div>
        </div>
      )}
    </div>
  )
}

function ChannelAliases({
  mapping, onChange,
}: { mapping: MappingSpec; onChange: (m: MappingSpec) => void }) {
  const [raw, setRaw] = useState('网店=线上, 门店=线下')
  function apply() {
    const aliases: Record<string, string> = {}
    raw.split(/[,，;；]/).map((p) => p.trim()).filter(Boolean).forEach((pair) => {
      const [k, v] = pair.split('=').map((s) => s?.trim())
      if (k && v) aliases[k] = v
    })
    onChange({ ...mapping, channel_aliases: aliases })
  }
  const current = Object.entries(mapping.channel_aliases)
    .map(([k, v]) => `${k}=${v}`).join(', ')
  return (
    <div className="form-row">
      <input value={raw} onChange={(e) => setRaw(e.target.value)} style={{ maxWidth: 360 }}
        placeholder="原始渠道=标准渠道，逗号分隔" />
      <button onClick={apply}>应用别名</button>
      {current && <span className="hint">当前：{current}</span>}
    </div>
  )
}

function dimNameGuess(col: number, preview: SheetPreview | null): string {
  // 取该列第一个非空表头文本作为维度名建议
  if (!preview) return `维度${col}`
  for (const row of preview.rows) {
    const cell = row[col - 1]
    if (cell && cell.v !== null && cell.v !== '') return String(cell.v)
  }
  return `维度${col}`
}

function describe(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as any
    if (d?.detail?.message) return d.detail.message
    if (d?.message) return d.message
    if (typeof d === 'string') return d
    return `请求失败（HTTP ${e.status}）`
  }
  return e instanceof Error ? e.message : String(e)
}
