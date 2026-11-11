import { useState } from 'react'
import type { IssueView, ReconView, RecordView } from './types'

const SOURCE_LABEL: Record<string, string> = {
  literal: '字面值',
  formula_cache: '公式缓存',
  missing: '缺失',
  unparseable: '无法解析',
  formula_no_cache: '公式无缓存',
}

function fmt(n: number | null): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function IssuesPanel({ issues, onLocate }: { issues: IssueView[]; onLocate: (coord: string) => void }) {
  if (!issues.length) return <p className="hint">没有问题，所有单元格都正常解析。</p>
  return (
    <div className="scroll-box">
      {issues.map((i, idx) => (
        <div className="issue-item" key={idx}>
          <span className={`badge ${i.severity}`}>
            {i.severity === 'error' ? '阻断' : i.severity === 'warning' ? '警告' : '提示'}
          </span>
          <a className="coord mono" onClick={() => onLocate(i.coordinate)}>{i.coordinate}</a>
          <span className="msg">{i.message}</span>
          {i.raw && <span className="raw mono">{i.raw}</span>}
        </div>
      ))}
    </div>
  )
}

function ReconPanel({ items, onLocate }: { items: ReconView[]; onLocate: (coord: string) => void }) {
  if (!items.length) return <p className="hint">未识别到合计/小计行。</p>
  return (
    <div className="scroll-box">
      <table className="data">
        <thead>
          <tr>
            <th>合计行</th><th>来源坐标</th><th>月份</th><th>渠道</th>
            <th className="num">原表合计（元）</th>
            <th className="num">明细求和（元）</th>
            <th className="num">差异</th>
            <th className="num">明细条数</th><th>结果</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r, idx) => (
            <tr key={idx} className={r.matched ? '' : 'mismatch'}>
              <td>{r.label}（第{r.total_row}行）</td>
              <td><a className="coord mono" onClick={() => onLocate(r.coordinate)}>{r.coordinate}</a></td>
              <td>{r.month}</td>
              <td>{r.channel}</td>
              <td className="num">{fmt(r.source_amount)}</td>
              <td className="num">{fmt(r.computed_amount)}</td>
              <td className="num">{r.diff === null ? '—' : fmt(r.diff)}</td>
              <td className="num">{r.detail_row_count}</td>
              <td>{r.matched ? <span className="badge ok">一致</span> : <span className="badge error">差异</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RecordsPanel({ records, onLocate }: { records: RecordView[]; onLocate: (coord: string) => void }) {
  if (!records.length) return <p className="hint">没有展开出明细记录。</p>
  const dimNames = Array.from(
    records.reduce((set, r) => {
      Object.keys(r.dimensions).forEach((k) => set.add(k))
      return set
    }, new Set<string>()),
  )
  return (
    <div className="scroll-box">
      <table className="data">
        <thead>
          <tr>
            {dimNames.map((d) => <th key={d}>{d}</th>)}
            <th>月份</th><th>渠道</th><th className="num">金额（元）</th>
            <th>单位</th><th>来源</th><th>溯源坐标</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r, idx) => (
            <tr key={idx}>
              {dimNames.map((d) => <td key={d}>{r.dimensions[d] || ''}</td>)}
              <td>{r.month}</td>
              <td>{r.channel}</td>
              <td className="num">{r.amount_yuan === null ? '缺失' : fmt(r.amount_yuan)}</td>
              <td>{r.unit}</td>
              <td><span className="badge src">{SOURCE_LABEL[r.value_source] ?? r.value_source}</span></td>
              <td><a className="coord mono" onClick={() => onLocate(r.coordinate)}>{r.coordinate}</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ResultTabs({
  issues, reconciliation, records, onLocate,
}: {
  issues: IssueView[]
  reconciliation: ReconView[]
  records: RecordView[]
  onLocate: (coord: string) => void
}) {
  const [tab, setTab] = useState<'recon' | 'records' | 'issues'>('recon')
  const mismatch = reconciliation.filter((r) => !r.matched).length
  const errors = issues.filter((i) => i.severity === 'error').length
  return (
    <div>
      <div className="tabs">
        <button className={`tab ${tab === 'recon' ? 'on' : ''}`} onClick={() => setTab('recon')}>
          合计核对 {mismatch > 0 && <span className="badge error" style={{ marginLeft: 6 }}>{mismatch} 项差异</span>}
        </button>
        <button className={`tab ${tab === 'records' ? 'on' : ''}`} onClick={() => setTab('records')}>
          展开明细（{records.length} 条预览）
        </button>
        <button className={`tab ${tab === 'issues' ? 'on' : ''}`} onClick={() => setTab('issues')}>
          问题清单 {errors > 0 && <span className="badge error" style={{ marginLeft: 6 }}>{errors} 阻断</span>}
        </button>
      </div>
      {tab === 'recon' && <ReconPanel items={reconciliation} onLocate={onLocate} />}
      {tab === 'records' && <RecordsPanel records={records} onLocate={onLocate} />}
      {tab === 'issues' && <IssuesPanel issues={issues} onLocate={onLocate} />}
    </div>
  )
}
