import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Badge, Button, Card, Empty, ErrorText, Field, formatDate, inputClass } from '../components/ui'
import type { CustomerUploadResult, IngestBatch, IngestPreview, IngestResult, Source } from '../types'

const CUSTOMER_OPTION = 'EXISTING_CUSTOMERS'

export default function IngestPage() {
  const { meta } = useAuth()
  const [sources, setSources] = useState<Source[]>([])
  const [sourceCode, setSourceCode] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [periodLabel, setPeriodLabel] = useState('')
  const [regionOverride, setRegionOverride] = useState('')
  const [preview, setPreview] = useState<IngestPreview | null>(null)
  const [result, setResult] = useState<IngestResult | CustomerUploadResult | null>(null)
  const [batches, setBatches] = useState<IngestBatch[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const isCustomer = sourceCode === CUSTOMER_OPTION
  const isMoef = sourceCode === 'SRC_MOEF_DESIGNATION'
  const isNpo = sourceCode === 'SRC_DATA_GO_KR_NPO'

  const loadBatches = useCallback(() => {
    api.get<IngestBatch[]>('/ingest/batches').then(setBatches).catch(() => setBatches([]))
  }, [])

  useEffect(() => {
    api.get<Source[]>('/ingest/sources').then((s) => {
      setSources(s)
      setSourceCode(s[0]?.code ?? '')
    }).catch((e) => setError(e.message))
    loadBatches()
  }, [loadBatches])

  function reset() {
    setPreview(null)
    setResult(null)
    setError('')
  }

  async function runPreview() {
    if (!file) return
    setBusy(true)
    reset()
    try {
      const fd = new FormData()
      fd.append('source_code', sourceCode)
      fd.append('file', file)
      if (regionOverride) fd.append('region_override', regionOverride)
      setPreview(await api.post<IngestPreview>('/ingest/preview', fd))
    } catch (e) {
      setError(e instanceof Error ? e.message : '미리보기 실패')
    } finally {
      setBusy(false)
    }
  }

  async function commit() {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (isCustomer) {
        setResult(await api.post<CustomerUploadResult>('/ingest/existing-customers', fd))
      } else {
        fd.append('source_code', sourceCode)
        if (periodLabel) fd.append('period_label', periodLabel)
        if (regionOverride) fd.append('region_override', regionOverride)
        setResult(await api.post<IngestResult>('/ingest/commit', fd))
      }
      setPreview(null)
      loadBatches()
    } catch (e) {
      setError(e instanceof Error ? e.message : '처리 실패')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold text-slate-800">데이터 업로드</h1>

      <Card title="1. 소스 선택 및 파일 업로드">
        <div className="grid grid-cols-3 gap-3">
          <Field label="소스">
            <select
              className={inputClass}
              value={sourceCode}
              onChange={(e) => {
                setSourceCode(e.target.value)
                reset()
              }}
            >
              {sources.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
              <option value={CUSTOMER_OPTION}>기고객 명단 (업셀·중복제거용)</option>
            </select>
          </Field>

          {isMoef && (
            <Field label="기간 (period_label) *" hint="예: 2026Q2 — 직전 분기 배치와 비교해 신규 건만 리드로 만듭니다.">
              <input className={inputClass} value={periodLabel} onChange={(e) => setPeriodLabel(e.target.value)} placeholder="2026Q2" />
            </Field>
          )}

          {isNpo && (
            <Field label="지역 보정 (선택)" hint="파일 주소가 시군구부터 시작할 때 시도를 지정합니다.">
              <select className={inputClass} value={regionOverride} onChange={(e) => setRegionOverride(e.target.value)}>
                <option value="">사용 안 함</option>
                {meta?.regions.filter((r) => r.code !== '99').map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
              </select>
            </Field>
          )}

          <Field label="파일" hint="xlsx / xls / csv (최대 30MB)">
            <input
              type="file"
              accept=".xlsx,.xls,.csv"
              className="w-full text-sm"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                reset()
              }}
            />
          </Field>
        </div>

        <div className="mt-4 flex gap-2">
          {!isCustomer && (
            <Button variant="secondary" disabled={!file || busy} onClick={runPreview}>
              {busy ? '분석 중…' : '파싱 미리보기'}
            </Button>
          )}
          <Button disabled={!file || busy || (isMoef && !periodLabel)} onClick={commit}>
            확정 처리
          </Button>
        </div>
        <div className="mt-3"><ErrorText>{error}</ErrorText></div>
      </Card>

      {preview && (
        <Card title={`2. 파싱 미리보기 — 총 ${preview.total_rows}행${preview.sheet_name ? ` (시트: ${preview.sheet_name})` : ''}`}>
          {preview.problems.length > 0 && (
            <ul className="mb-3 space-y-1 rounded bg-amber-50 p-3 text-sm text-amber-900">
              {preview.problems.map((p, i) => <li key={i}>• {p}</li>)}
            </ul>
          )}
          <div className="mb-3 flex flex-wrap gap-1 text-xs">
            {Object.entries(preview.header_map).map(([std, header]) => (
              <Badge key={std} tone="blue">{header} → {std}</Badge>
            ))}
            {preview.unmapped_headers.map((h) => <Badge key={h}>{h} → (미매핑)</Badge>)}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="py-1">행</th>
                  <th className="py-1">법인명</th>
                  <th className="py-1">유형</th>
                  <th className="py-1">지역</th>
                  <th className="py-1">법인등록번호</th>
                  <th className="py-1">지정/설립일</th>
                  <th className="py-1">문제</th>
                </tr>
              </thead>
              <tbody>
                {preview.preview_rows.map((r) => (
                  <tr key={r.row_no} className={`border-b border-slate-50 ${r.error ? 'bg-rose-50' : ''}`}>
                    <td className="py-1">{r.row_no}</td>
                    <td className="py-1 font-medium">{r.mapped?.org_name ?? '-'}</td>
                    <td className="py-1">{r.mapped?.org_type ?? '-'}</td>
                    <td className="py-1">{r.mapped?.region_code ?? '-'} {r.mapped?.district ?? ''}</td>
                    <td className="py-1">{r.mapped?.corp_reg_no ?? '-'}</td>
                    <td className="py-1">{r.mapped?.designated_at ?? r.mapped?.established_at ?? '-'}</td>
                    <td className="py-1 text-rose-600">{r.error ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4">
            <Button disabled={busy || (isMoef && !periodLabel)} onClick={commit}>확정 처리</Button>
          </div>
        </Card>
      )}

      {result && (
        <Card title="3. 처리 결과">
          {'new_leads' in result ? (
            <>
              <div className="grid grid-cols-6 gap-3 text-center">
                {[
                  ['총 행수', result.total_rows],
                  ['신규 리드', result.new_leads],
                  ['병합', result.merged_leads],
                  ['중복 스킵', result.dup_skipped],
                  ['기고객', result.customer_skipped],
                  ['에러', result.error_rows],
                ].map(([k, v]) => (
                  <div key={String(k)} className="rounded bg-slate-50 p-3">
                    <p className="text-xs text-slate-500">{k}</p>
                    <p className="text-lg font-bold text-slate-800">{v}</p>
                  </div>
                ))}
              </div>
              {result.revoked_marked > 0 && (
                <p className="mt-3 text-sm text-amber-800">
                  누계에서 사라진 {result.revoked_marked}건에 '지정취소 가능' 플래그를 표시했습니다.
                </p>
              )}
              {result.warnings.map((w, i) => <p key={i} className="mt-2 text-sm text-amber-800">⚠ {w}</p>)}
              {result.errors.length > 0 && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-sm text-rose-700">에러 행 {result.errors.length}건 보기</summary>
                  <ul className="mt-2 space-y-1 text-xs text-slate-600">
                    {result.errors.slice(0, 100).map((e, i) => (
                      <li key={i}>{e.row_no ?? '-'}행: {e.message}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          ) : (
            <div className="grid grid-cols-5 gap-3 text-center">
              {[
                ['총 행수', result.total_rows],
                ['신규 등록', result.inserted],
                ['갱신', result.updated],
                ['에러', result.error_rows],
                ['재태깅된 리드', result.retagged_leads],
              ].map(([k, v]) => (
                <div key={String(k)} className="rounded bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">{k}</p>
                  <p className="text-lg font-bold text-slate-800">{v}</p>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      <Card title="배치 이력">
        {batches.length === 0 ? (
          <Empty>업로드 이력이 없습니다.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2">일시</th>
                <th className="py-2">소스</th>
                <th className="py-2">파일명</th>
                <th className="py-2">기간</th>
                <th className="py-2 text-right">총행</th>
                <th className="py-2 text-right">신규</th>
                <th className="py-2 text-right">병합</th>
                <th className="py-2 text-right">중복</th>
                <th className="py-2 text-right">기고객</th>
                <th className="py-2 text-right">에러</th>
                <th className="py-2">상태</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id} className="border-b border-slate-50">
                  <td className="py-1.5 text-xs">{formatDate(b.created_at)}</td>
                  <td className="py-1.5 text-xs">{b.source_name}</td>
                  <td className="py-1.5 text-xs">{b.file_name}</td>
                  <td className="py-1.5 text-xs">{b.period_label ?? '-'}</td>
                  <td className="py-1.5 text-right">{b.total_rows}</td>
                  <td className="py-1.5 text-right font-medium">{b.new_leads}</td>
                  <td className="py-1.5 text-right">{b.merged_leads}</td>
                  <td className="py-1.5 text-right">{b.dup_skipped}</td>
                  <td className="py-1.5 text-right">{b.customer_skipped}</td>
                  <td className="py-1.5 text-right text-rose-600">{b.error_rows}</td>
                  <td className="py-1.5">
                    <Badge tone={b.status === 'PARSED' ? 'green' : b.status === 'FAILED' ? 'red' : 'slate'}>
                      {b.status}
                    </Badge>
                    {b.error_message && <p className="text-xs text-rose-600">{b.error_message}</p>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
