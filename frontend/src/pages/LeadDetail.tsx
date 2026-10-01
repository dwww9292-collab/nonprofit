import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth, useLabels } from '../auth'
import {
  Badge, Button, Card, Empty, ErrorText, Field, GradeBadge, Modal,
  formatDate, formatMoney, inputClass,
} from '../components/ui'
import type { Activity, AssigneeSuggestion, Deal, LeadDetail } from '../types'

/** NSM 사업자번호는 숫자 10자리로 들어온다. 사람이 NSM 에 그대로 붙여넣으므로 서식을 준다. */
function formatBizNo(value: string | null): string {
  if (!value) return '-'
  const digits = value.replace(/\D/g, '')
  return digits.length === 10
    ? `${digits.slice(0, 3)}-${digits.slice(3, 5)}-${digits.slice(5)}`
    : value
}

export default function LeadDetailPage() {
  const { id } = useParams()
  const { user, meta, can } = useAuth()
  const label = useLabels()
  const managerUp = can('ADMIN', 'MANAGER')

  const [lead, setLead] = useState<LeadDetail | null>(null)
  const [deals, setDeals] = useState<Deal[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [error, setError] = useState('')
  const [modal, setModal] = useState<'activity' | 'deal' | 'assign' | 'lost' | 'edit' | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    try {
      const [l, d, a] = await Promise.all([
        api.get<LeadDetail>(`/leads/${id}`),
        api.get<Deal[]>(`/deals?lead_id=${id}`),
        api.get<Activity[]>(`/leads/${id}/activities`),
      ])
      setLead(l)
      setDeals(d)
      setActivities(a)
    } catch (e) {
      setError(e instanceof Error ? e.message : '불러오지 못했습니다.')
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  if (error) return <ErrorText>{error}</ErrorText>
  if (!lead) return <p className="text-sm text-slate-500">불러오는 중…</p>

  const canEdit = managerUp || lead.assignee_id === user?.id
  const breakdown = Object.entries(lead.score_breakdown ?? {}).filter(([k]) => k !== 'total')
  const maxPoints = Math.max(10, ...breakdown.map(([, v]) => Math.abs(v)))

  async function changeStatus(status: string, lost_reason?: string) {
    try {
      setLead(await api.patch<LeadDetail>(`/leads/${lead!.id}/status`, { status, lost_reason: lost_reason ?? null }))
      setModal(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '상태 변경 실패')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/leads" className="text-xs text-slate-500 underline">← 리드 목록</Link>
          <h1 className="mt-1 flex items-center gap-2 text-lg font-bold text-slate-800">
            <GradeBadge grade={lead.grade} score={lead.score} />
            {lead.org_name}
            {lead.is_existing_customer && <Badge tone="green">기고객</Badge>}
            {lead.possible_dup_lead_id && (
              <Link to={`/leads/${lead.possible_dup_lead_id}`}><Badge tone="amber">중복의심 →</Badge></Link>
            )}
            {lead.possible_revoked && <Badge tone="red">지정취소 가능</Badge>}
            {lead.designated_at && <Badge tone="blue">공익법인 지정</Badge>}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <select
            className={`${inputClass} w-36`}
            value={lead.status}
            disabled={!canEdit}
            onChange={(e) => (e.target.value === 'LOST' ? setModal('lost') : changeStatus(e.target.value))}
          >
            {meta?.lead_statuses.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
          {managerUp && <Button variant="secondary" onClick={() => setModal('assign')}>담당자 배정</Button>}
          {canEdit && <Button variant="secondary" onClick={() => setModal('edit')}>수정</Button>}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* 좌: 기본정보 */}
        <Card title="기본정보">
          <dl className="space-y-2 text-sm">
            {[
              ['유형', label('org_types', lead.org_type)],
              ['지역', `${label('regions', lead.region_code)} ${lead.district ?? ''}`],
              ['주소', lead.address ?? '-'],
              ['대표자', lead.representative ?? '-'],
              ['연락처', lead.phone ?? '-'],
              ['이메일', lead.email ?? '-'],
              ['설립허가일', formatDate(lead.established_at)],
              ['공익법인 지정일', formatDate(lead.designated_at)],
              ['주무관청', lead.authority ?? '-'],
              ['자산규모', label('asset_sizes', lead.asset_size)],
              ['법인등록번호', lead.corp_reg_no ?? '-'],
              ['사업자/고유번호', lead.biz_reg_no ?? '-'],
              ['수집일', formatDate(lead.collected_at)],
              ['담당자', lead.assignee_name ?? '미배정'],
            ].map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <dt className="w-24 shrink-0 text-xs text-slate-500">{k}</dt>
                <dd className="text-slate-700">{v}</dd>
              </div>
            ))}
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-xs text-slate-500">홈페이지</dt>
              <dd>
                {lead.homepage_url ? (
                  <a href={lead.homepage_url} target="_blank" rel="noreferrer" className="text-sky-700 underline">
                    {lead.homepage_url}
                  </a>
                ) : (
                  <span className="text-emerald-700">없음 (구축 영업 기회)</span>
                )}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-xs text-slate-500">설립목적</dt>
              <dd className="text-slate-700">{lead.purpose ?? '-'}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-xs text-slate-500">소스</dt>
              <dd className="flex flex-wrap gap-1">
                {lead.sources.map((s) => <Badge key={s.id}>{s.name}</Badge>)}
              </dd>
            </div>
            {lead.memo && (
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-xs text-slate-500">메모</dt>
                <dd className="whitespace-pre-wrap text-slate-700">{lead.memo}</dd>
              </div>
            )}
          </dl>
        </Card>

        {/* 중: NSM 제품 + 스코어 + 딜 */}
        <div className="space-y-4">
          <Card title="더존 제품 보유 현황 (NSM)">
            {lead.nsm_matched ? (
              <dl className="space-y-2 text-sm">
                {lead.upsell_path && (
                  <div className="mb-3 rounded bg-slate-50 p-2">
                    <p className="text-xs text-slate-500">상향 경로</p>
                    <p className="font-medium text-slate-800">{lead.upsell_path}</p>
                    {lead.upsell_priority != null && (
                      <Badge tone={lead.upsell_priority === 1 ? 'red' : lead.upsell_priority === 2 ? 'amber' : 'blue'}>
                        영업 {lead.upsell_priority}순위
                      </Badge>
                    )}
                  </div>
                )}
                {[
                  ['보유 제품', lead.nsm_products ?? '-'],
                  ['주력 제품', lead.nsm_top_product || '-'],
                  ['NSM 회사명', lead.nsm_company_name ?? '-'],
                  ['사업자번호', formatBizNo(lead.nsm_biz_reg_no)],
                  ['거래처코드', lead.nsm_customer_code ?? '-'],
                  ['NSM 영업담당', lead.nsm_sales_owner ?? '-'],
                ].map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <dt className="w-24 shrink-0 text-xs text-slate-500">{k}</dt>
                    <dd className="text-slate-700">{v}</dd>
                  </div>
                ))}
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-xs text-slate-500">매칭 근거</dt>
                  <dd className="text-xs text-slate-600">
                    {lead.nsm_match_basis ?? '-'}
                    {lead.nsm_match_confidence && (
                      <Badge tone={lead.nsm_match_confidence === '높음' ? 'green' : lead.nsm_match_confidence === '중간' ? 'blue' : 'amber'}>
                        신뢰도 {lead.nsm_match_confidence}
                      </Badge>
                    )}
                  </dd>
                </div>
                {lead.nsm_match_confidence === '확인필요' && (
                  <p className="rounded bg-amber-50 p-2 text-xs text-amber-900">
                    동명 법인이 여러 건이거나 법인격이 어긋납니다. 영업 전에 사업자번호로 확인하세요.
                  </p>
                )}
                <p className="pt-1 text-[11px] text-slate-400">
                  NSM 동기화: {formatDate(lead.nsm_synced_at)}
                </p>
              </dl>
            ) : (
              <div className="text-sm">
                <p className="text-emerald-700">NSM에 없는 단체입니다 — 신규 개척 대상.</p>
                <p className="mt-1 text-xs text-slate-500">
                  단체명·대표전화·시도·법인격으로 대조한 결과입니다. 표기가 달라 못 찾았을 수 있으니
                  사업자번호를 알게 되면 NSM에서 직접 조회해 보세요.
                </p>
                {lead.nsm_synced_at && (
                  <p className="pt-2 text-[11px] text-slate-400">NSM 동기화: {formatDate(lead.nsm_synced_at)}</p>
                )}
              </div>
            )}
          </Card>

          <Card title="리드 스코어">
            <div className="mb-3 flex items-baseline gap-2">
              <span className="text-3xl font-bold text-slate-800">{lead.score}</span>
              <span className="text-sm text-slate-500">/ 100</span>
              <GradeBadge grade={lead.grade} />
            </div>
            <ul className="space-y-1.5">
              {breakdown.map(([key, value]) => (
                <li key={key} className="flex items-center gap-2 text-xs">
                  <span className="w-40 shrink-0 text-slate-600">{key}</span>
                  <div className="h-3 flex-1 rounded bg-slate-100">
                    <div
                      className={`h-3 rounded ${value < 0 ? 'bg-rose-400' : 'bg-slate-600'}`}
                      style={{ width: `${(Math.abs(value) / maxPoints) * 100}%` }}
                    />
                  </div>
                  <span className={`w-8 text-right ${value < 0 ? 'text-rose-600' : 'text-slate-700'}`}>{value}</span>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex gap-2">
              {meta?.external_links.map((l) => (
                <a
                  key={l.code}
                  href={l.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  {l.label} ↗
                </a>
              ))}
            </div>
          </Card>

          <Card title="딜" action={canEdit && <Button variant="ghost" onClick={() => setModal('deal')}>딜 추가 +</Button>}>
            {deals.length === 0 ? (
              <Empty>등록된 딜이 없습니다.</Empty>
            ) : (
              <ul className="space-y-2">
                {deals.map((d) => (
                  <li key={d.id} className="rounded border border-slate-200 p-2 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-700">{label('products', d.product_code)}</span>
                      <Badge tone={d.stage === 'WON' ? 'green' : d.stage === 'LOST' ? 'red' : 'blue'}>
                        {label('deal_stages', d.stage)}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {formatMoney(d.amount)} · 확률 {d.probability ?? '-'}% · 예상마감 {formatDate(d.expected_close)}
                      {d.owner_name && ` · ${d.owner_name}`}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {/* 우: 활동 타임라인 */}
        <Card title="활동 타임라인" action={canEdit && <Button variant="ghost" onClick={() => setModal('activity')}>활동 추가 +</Button>}>
          {activities.length === 0 ? (
            <Empty>활동 기록이 없습니다.</Empty>
          ) : (
            <ol className="space-y-3">
              {activities.map((a) => (
                <li key={a.id} className="border-l-2 border-slate-200 pl-3 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge tone="blue">{label('activity_types', a.type)}</Badge>
                    <span className="text-xs text-slate-500">
                      {formatDate(a.occurred_at)} · {a.actor_name}
                    </span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-slate-700">{a.summary}</p>
                  {a.next_action && (
                    <p className="mt-1 text-xs text-slate-500">
                      다음: {a.next_action} {a.next_action_at && `(${formatDate(a.next_action_at)})`}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      {modal === 'activity' && <ActivityModal leadId={lead.id} deals={deals} onClose={() => setModal(null)} onDone={load} />}
      {modal === 'deal' && <DealModal leadId={lead.id} onClose={() => setModal(null)} onDone={load} />}
      {modal === 'assign' && <AssignModal leadId={lead.id} onClose={() => setModal(null)} onDone={load} />}
      {modal === 'lost' && <LostModal onClose={() => setModal(null)} onSubmit={(r) => changeStatus('LOST', r)} />}
      {modal === 'edit' && <EditModal lead={lead} onClose={() => setModal(null)} onDone={load} />}
    </div>
  )
}

function ActivityModal({ leadId, deals, onClose, onDone }: {
  leadId: number; deals: Deal[]; onClose: () => void; onDone: () => void
}) {
  const { meta } = useAuth()
  const [form, setForm] = useState({ type: 'CALL', summary: '', next_action: '', next_action_at: '', deal_id: '' })
  const [error, setError] = useState('')

  async function submit() {
    try {
      await api.post(`/leads/${leadId}/activities`, {
        type: form.type,
        summary: form.summary,
        next_action: form.next_action || null,
        next_action_at: form.next_action_at ? new Date(form.next_action_at).toISOString() : null,
        deal_id: form.deal_id ? Number(form.deal_id) : null,
      })
      onDone()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  return (
    <Modal title="활동 추가" onClose={onClose}>
      <div className="space-y-3">
        <Field label="유형">
          <select className={inputClass} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {meta?.activity_types.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="요약 *">
          <textarea className={inputClass} rows={3} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
        </Field>
        {deals.length > 0 && (
          <Field label="관련 딜">
            <select className={inputClass} value={form.deal_id} onChange={(e) => setForm({ ...form, deal_id: e.target.value })}>
              <option value="">선택 안 함</option>
              {deals.map((d) => <option key={d.id} value={d.id}>{d.product_code} · {d.stage}</option>)}
            </select>
          </Field>
        )}
        <Field label="다음 액션">
          <input className={inputClass} value={form.next_action} onChange={(e) => setForm({ ...form, next_action: e.target.value })} />
        </Field>
        <Field label="차기 일정">
          <input type="datetime-local" className={inputClass} value={form.next_action_at} onChange={(e) => setForm({ ...form, next_action_at: e.target.value })} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>취소</Button>
          <Button disabled={!form.summary.trim()} onClick={submit}>저장</Button>
        </div>
      </div>
    </Modal>
  )
}

function DealModal({ leadId, onClose, onDone }: { leadId: number; onClose: () => void; onDone: () => void }) {
  const { meta } = useAuth()
  const [form, setForm] = useState({ product_code: 'BUNDLE_ERP_HP', stage: 'CONTACT', amount: '', probability: '40', expected_close: '' })
  const [error, setError] = useState('')

  async function submit() {
    try {
      await api.post('/deals', {
        lead_id: leadId,
        product_code: form.product_code,
        stage: form.stage,
        amount: form.amount ? Number(form.amount) : null,
        probability: form.probability ? Number(form.probability) : null,
        expected_close: form.expected_close || null,
      })
      onDone()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  return (
    <Modal title="딜 추가" onClose={onClose}>
      <div className="space-y-3">
        <Field label="상품">
          <select className={inputClass} value={form.product_code} onChange={(e) => setForm({ ...form, product_code: e.target.value })}>
            {meta?.products.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="단계">
          <select className={inputClass} value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })}>
            {meta?.deal_stages.filter((o) => o.code !== 'LOST').map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="예상금액 (원)">
          <input type="number" className={inputClass} value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
        </Field>
        <Field label="확률 (%)">
          <select className={inputClass} value={form.probability} onChange={(e) => setForm({ ...form, probability: e.target.value })}>
            {[20, 40, 60, 80, 100].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
        <Field label="예상 마감일">
          <input type="date" className={inputClass} value={form.expected_close} onChange={(e) => setForm({ ...form, expected_close: e.target.value })} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>취소</Button>
          <Button onClick={submit}>저장</Button>
        </div>
      </div>
    </Modal>
  )
}

function AssignModal({ leadId, onClose, onDone }: { leadId: number; onClose: () => void; onDone: () => void }) {
  const [rows, setRows] = useState<AssigneeSuggestion[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<AssigneeSuggestion[]>(`/leads/${leadId}/assignee-suggestions`).then(setRows).catch((e) => setError(e.message))
  }, [leadId])

  async function assign(userId: number) {
    try {
      await api.post('/leads/assign', { lead_ids: [leadId], assignee_id: userId })
      onDone()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '배정 실패')
    }
  }

  return (
    <Modal title="담당자 배정" onClose={onClose}>
      <p className="mb-2 text-xs text-slate-500">담당 지역이 일치하는 사원을 상단에 제안합니다 (자동 배정 아님).</p>
      <ErrorText>{error}</ErrorText>
      <ul className="divide-y divide-slate-100">
        {rows.map((r) => (
          <li key={r.user_id} className="flex items-center justify-between py-2 text-sm">
            <span className="flex items-center gap-2">
              {r.name}
              {r.region_match && <Badge tone="green">지역 일치</Badge>}
              <span className="text-xs text-slate-500">진행 중 {r.open_lead_count}건</span>
            </span>
            <Button onClick={() => assign(r.user_id)}>배정</Button>
          </li>
        ))}
      </ul>
    </Modal>
  )
}

function LostModal({ onClose, onSubmit }: { onClose: () => void; onSubmit: (reason: string) => void }) {
  const { meta } = useAuth()
  const [reason, setReason] = useState('LOST_NO_BUDGET')
  return (
    <Modal title="실패 처리 사유" onClose={onClose}>
      <select className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)}>
        {meta?.lost_reasons.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
      </select>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>취소</Button>
        <Button variant="danger" onClick={() => onSubmit(reason)}>실패 처리</Button>
      </div>
    </Modal>
  )
}

function EditModal({ lead, onClose, onDone }: { lead: LeadDetail; onClose: () => void; onDone: () => void }) {
  const { meta } = useAuth()
  const [form, setForm] = useState({
    org_name: lead.org_name,
    org_type: lead.org_type,
    address: lead.address ?? '',
    representative: lead.representative ?? '',
    phone: lead.phone ?? '',
    email: lead.email ?? '',
    homepage_url: lead.homepage_url ?? '',
    authority: lead.authority ?? '',
    asset_size: lead.asset_size,
    established_at: lead.established_at ?? '',
    designated_at: lead.designated_at ?? '',
    memo: lead.memo ?? '',
  })
  const [error, setError] = useState('')

  async function submit() {
    try {
      await api.patch(`/leads/${lead.id}`, Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, v === '' ? null : v]),
      ))
      onDone()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  return (
    <Modal title="리드 수정" onClose={onClose} wide>
      <div className="grid grid-cols-2 gap-3">
        <Field label="법인명"><input className={inputClass} value={form.org_name} onChange={(e) => setForm({ ...form, org_name: e.target.value })} /></Field>
        <Field label="유형">
          <select className={inputClass} value={form.org_type} onChange={(e) => setForm({ ...form, org_type: e.target.value })}>
            {meta?.org_types.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="주소"><input className={inputClass} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
        <Field label="대표자"><input className={inputClass} value={form.representative} onChange={(e) => setForm({ ...form, representative: e.target.value })} /></Field>
        <Field label="전화"><input className={inputClass} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
        <Field label="이메일"><input className={inputClass} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="홈페이지"><input className={inputClass} value={form.homepage_url} onChange={(e) => setForm({ ...form, homepage_url: e.target.value })} /></Field>
        <Field label="주무관청"><input className={inputClass} value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })} /></Field>
        <Field label="설립허가일"><input type="date" className={inputClass} value={form.established_at} onChange={(e) => setForm({ ...form, established_at: e.target.value })} /></Field>
        <Field label="지정일"><input type="date" className={inputClass} value={form.designated_at} onChange={(e) => setForm({ ...form, designated_at: e.target.value })} /></Field>
        <Field label="자산규모">
          <select className={inputClass} value={form.asset_size} onChange={(e) => setForm({ ...form, asset_size: e.target.value })}>
            {meta?.asset_sizes.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <div className="col-span-2">
          <Field label="메모"><textarea className={inputClass} rows={2} value={form.memo} onChange={(e) => setForm({ ...form, memo: e.target.value })} /></Field>
        </div>
      </div>
      <div className="mt-3"><ErrorText>{error}</ErrorText></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>취소</Button>
        <Button onClick={submit}>저장</Button>
      </div>
    </Modal>
  )
}
