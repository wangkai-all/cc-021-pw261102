// 后端接口对应的类型定义

export interface SheetMeta {
  name: string
  max_row: number
  max_col: number
  merge_count: number
}

export interface UploadResponse {
  workbook_id: string
  original_name: string
  sheets: SheetMeta[]
}

export interface PreviewCell {
  v: string | number | null
  f: boolean        // 是否公式
  hc: boolean       // 公式是否有缓存值
  raw?: string | null
}

export interface MergeInfo {
  min_row: number
  max_row: number
  min_col: number
  max_col: number
  anchor_value: unknown
}

export interface SheetPreview {
  sheet: string
  max_row: number
  max_col: number
  shown_rows: number
  shown_cols: number
  col_letters: string[]
  rows: PreviewCell[][]
  merges: MergeInfo[]
}

export interface Rect {
  row_start: number
  row_end: number
  col_start: number
  col_end: number
}

export interface DimColumnSpec {
  col: number
  row_start: number
  row_end: number
  name: string
}

export interface MappingSpec {
  name: string
  sheet_name: string
  report_year: number
  unit: string
  header: Rect
  data: Rect
  dimensions: DimColumnSpec[]
  channel_aliases: Record<string, string>
}

export interface HeaderColumnView {
  col: number
  path: string[]
  month: string
  month_display: string
  channel: string
  channel_raw: string
  coordinate: string
}

export interface TotalRowView {
  row: number
  label: string
  kind: string
  coordinates: Record<string, string>
  values: Record<string, unknown>
}

export interface IssueView {
  severity: 'error' | 'warning' | 'info'
  code: string
  coordinate: string
  message: string
  raw: string | null
}

export interface ReconView {
  label: string
  total_row: number
  coordinate: string
  month: string
  channel: string
  source_amount: number | null
  computed_amount: number | null
  diff: number | null
  matched: boolean
  detail_row_count: number
}

export interface RecordView {
  dimensions: Record<string, string>
  month: string
  channel: string
  amount_yuan: number | null
  unit: string
  value_source: string
  workbook_path: string
  sheet_name: string
  coordinate: string
  row: number
  col: number
  formula_text: string | null
}

export interface ExtractSummary {
  record_count: number
  issue_count: number
  error_count: number
  total_row_count: number
  reconcile_mismatch_count: number
}

export interface PreviewExtractResponse {
  fingerprint: string
  summary: ExtractSummary
  header_columns: HeaderColumnView[]
  total_rows: TotalRowView[]
  records: RecordView[]
  record_truncated: boolean
  issues: IssueView[]
  reconciliation: ReconView[]
}

export interface ReuseCheckResponse {
  structure_matches: boolean
  saved_fingerprint: string
  current_fingerprint: string
  mapping: MappingSpec
  preview: {
    summary: ExtractSummary
    header_columns: HeaderColumnView[]
    issues: IssueView[]
    reconciliation: ReconView[]
  }
}

export interface MappingListItem {
  name: string
  sheet_name: string
  report_year: number
  unit: string
  fingerprint: string
  updated_at: string
}

export interface CommitResponse {
  import_id: string
  workbook_name: string
  fingerprint: string
  summary: ExtractSummary
  reconciliation: ReconView[]
}
