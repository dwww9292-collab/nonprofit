import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Badge, Button, ErrorText, Field, Modal, inputClass } from '../components/ui'
import type { DupCheckResponse, LeadDetail, Source } from '../types'

const EMPTY = {
  org_name: '',
  org_type: 'ORG_FOUNDATION',
  source_code: 'SRC_MANUAL',
  address: '',
  representative: '',
  phone: '',
  email: '',
  homepage_url: '',
  established_at: '',
  designated_at: '',
  purpose: '',
  authority: '',
  corp_reg_no: '',
  biz_reg_no: '',
  asset_size: 'ASSET_UNKNOWN',
  memo: '',
}

export default function ManualLeadForm({ onClose, onCreated }: { onClose: () => void; onCreated: (lead: LeadDetail) => void }) {
  const { meta } = useAuth()
  const [form, setForm] = useState({ ...EMPTY })
  const [sources, setSources] = useState<Source[]>([])
  const [dup, setDup] = useState<DupCheckResponse | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const timer = useRef<number>()

  useEffect(() => {
    api.get<Source[]>('/leads/meta/sources').then(setSources).catch(() => setSources([]))
  }, [])

  // 실시간 중복검사 (debounce 500ms — docs/04-data-sources.md 소스 3)
  useEffect(() => {
    window.clearTimeout(timer.current)
    if (form.org_name.trim().length < 2) {
      setDup(null)
      return
    }
    timer.current = window.setTimeout(() => {
      api
        .post<DupCheckResponse>('/leads/dup-check', {
          org_name: form.org_name,
          address: form.address || null,
          corp_reg_no: form.corp_reg_no || null,
          biz_reg_no: form.biz_reg_no || null,
        })
        .then(setDup)
        .catch(() => setDup(null))
    }, 500)
    return () => window.clearTimeout(timer.current)
  }, [form.org_name, form.address, form.corp_reg_no, form.biz_reg_no])

  function set(key: keyof typeof EMPTY, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function submit() {
    setBusy(true)
    setError('')
    try {
      const payload = Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, v === '' ? null : v]),
      )
      onCreated(await api.post<LeadDetail>('/leads', payload))
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="리드 수기입력" onClose={onClose} wide>
      <div className="grid grid-cols-3 gap-3">
        <Field label="법인/단체명 *">
          <input className={inputClass} value={form.org_name} onChange={(e) => set('org_name', e.target.value)} autoFocus />
        </Field>
        <Field label="유형 *">
          <select className={inputClass} value={form.org_type} onChange={(e) => set('org_type', e.target.value)}>
            {meta?.org_types.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="소스 *">
          <select className={inputClass} value={form.source_code} onChange={(e) => set('source_code', e.target.value)}>
            {sources.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
          </select>
        </Field>

        <Field label="주소">
          <input className={inputClass} value={form.address} onChange={(e) => set('address', e.target.value)} placeholder="시도명부터 입력하면 지역이 자동 분류됩니다" />
        </Field>
        <Field label="대표자">
          <input className={inputClass} value={form.representative} onChange={(e) => set('representative', e.target.value)} />
        </Field>
        <Field label="주무관청">
          <input className={inputClass} value={form.authority} onChange={(e) => set('authority', e.target.value)} />
        </Field>

        <Field label="전화">
          <input className={inputClass} value={form.phone} onChange={(e) => set('phone', e.target.value)} />
        </Field>
        <Field label="이메일">
          <input className={inputClass} value={form.email} onChange={(e) => set('email', e.target.value)} />
        </Field>
        <Field label="홈페이지">
          <input className={inputClass} value={form.homepage_url} onChange={(e) => set('homepage_url', e.target.value)} />
        </Field>

        <Field label="설립허가일">
          <input type="date" className={inputClass} value={form.established_at} onChange={(e) => set('established_at', e.target.value)} />
        </Field>
        <Field label="공익법인 지정일">
          <input type="date" className={inputClass} value={form.designated_at} onChange={(e) => set('designated_at', e.target.value)} />
        </Field>
        <Field label="자산규모">
          <select className={inputClass} value={form.asset_size} onChange={(e) => set('asset_size', e.target.value)}>
            {meta?.asset_sizes.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>

        <Field label="법인등록번호">
          <input className={inputClass} value={form.corp_reg_no} onChange={(e) => set('corp_reg_no', e.target.value)} placeholder="13자리" />
        </Field>
        <Field label="사업자/고유번호">
          <input className={inputClass} value={form.biz_reg_no} onChange={(e) => set('biz_reg_no', e.target.value)} placeholder="10자리" />
        </Field>
        <Field label="설립목적/주된사업">
          <input className={inputClass} value={form.purpose} onChange={(e) => set('purpose', e.target.value)} />
        </Field>

        <div className="col-span-3">
          <Field label="메모">
            <textarea className={inputClass} rows={2} value={form.memo} onChange={(e) => set('memo', e.target.value)} />
          </Field>
        </div>
      </div>

      {dup && (dup.exact || dup.similar.length > 0 || dup.existing_customer) && (
        <div className="mt-4 space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-medium text-amber-900">중복 가능성이 감지됐습니다</p>
          {dup.existing_customer && <Badge tone="green">이미 기고객 명단에 있는 법인입니다</Badge>}
          {[...(dup.exact ? [dup.exact] : []), ...dup.similar].map((c) => (
            <div key={c.lead_id} className="flex items-center justify-between rounded bg-white px-2 py-1">
              <span>
                <span className="font-medium">{c.org_name}</span>
                <span className="ml-2 text-xs text-slate-500">
                  {c.address ?? '주소 없음'} · {c.status} · {c.assignee_name ?? '미배정'} · {c.match_reason}
                </span>
              </span>
              <Link to={`/leads/${c.lead_id}`} className="text-xs text-sky-700 underline" onClick={onClose}>
                기존 리드로 이동
              </Link>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4">
        <ErrorText>{error}</ErrorText>
      </div>

      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>취소</Button>
        <Button disabled={busy || !form.org_name.trim()} onClick={submit}>
          {busy ? '저장 중…' : '저장'}
        </Button>
      </div>
    </Modal>
  )
}
