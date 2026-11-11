import type {
  CommitResponse,
  MappingListItem,
  MappingSpec,
  PreviewExtractResponse,
  ReuseCheckResponse,
  SheetPreview,
  UploadResponse,
} from './types'

async function jsonOrThrow(res: Response) {
  if (!res.ok) {
    let detail: unknown = null
    try {
      detail = await res.json()
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json()
}

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(`HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

export async function uploadWorkbook(file: File): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/workbooks/upload', { method: 'POST', body: form })
  return jsonOrThrow(res)
}

export async function fetchPreview(
  workbookId: string,
  sheet: string,
  maxRows = 80,
  maxCols = 40,
): Promise<SheetPreview> {
  const res = await fetch(
    `/api/workbooks/${encodeURIComponent(workbookId)}/sheets/${encodeURIComponent(sheet)}/preview`
      + `?max_rows=${maxRows}&max_cols=${maxCols}`,
  )
  return jsonOrThrow(res)
}

export async function previewExtract(
  workbookId: string,
  mapping: MappingSpec,
  persistMapping = false,
): Promise<PreviewExtractResponse> {
  const res = await fetch('/api/mappings/preview-extract', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workbook_id: workbookId, mapping, persist_mapping: persistMapping }),
  })
  return jsonOrThrow(res)
}

export async function reuseCheck(
  workbookId: string,
  mappingName: string,
): Promise<ReuseCheckResponse> {
  const res = await fetch('/api/mappings/reuse-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workbook_id: workbookId, mapping_name: mappingName }),
  })
  return jsonOrThrow(res)
}

export async function listMappings(): Promise<{ mappings: MappingListItem[] }> {
  const res = await fetch('/api/mappings')
  return jsonOrThrow(res)
}

export async function commitImport(
  workbookId: string,
  mapping: MappingSpec,
  saveMapping: boolean,
): Promise<CommitResponse> {
  const res = await fetch('/api/imports/commit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workbook_id: workbookId,
      mapping,
      mapping_name: mapping.name,
      save_mapping: saveMapping,
    }),
  })
  return jsonOrThrow(res)
}

export async function listImports() {
  const res = await fetch('/api/imports')
  return jsonOrThrow(res)
}

export async function fetchFacts(importId: string) {
  const res = await fetch(`/api/imports/${importId}/facts`)
  return jsonOrThrow(res)
}
