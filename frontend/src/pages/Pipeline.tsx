import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs } from '../api/client'
import { useAuth, useLabels } from '../auth'
import { Badge, Button, Card, ErrorText, Modal, formatDate, formatMoney, inputClass } from '../components/ui'
import type { Deal, User } from '../types'

const STAGES = ['CONTACT', 'MEETING', 'PROPOSAL', 'NEGOTIATION', 'WON', 'LOST'] as const
const COLLAPSIBLE = new Set(['WON', 'LOST'])

export default function PipelinePage() {
  const { user, meta } = useAuth()
  const label = useLabels()
  const [deals, setDeals] = useState<Deal[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set(['LOST']))
  const [dragged, setDragged] = useState<Deal | null>(null)
  const [lostTarget, setLostTarget] = useState<Deal | null>(null)
  const [filters, setFilters] = useState({
    owner_id: user?.role === 'SALES' ? String(user.id) : '',
    product_code: '',
    amount_min: '',
    amount_max: '',
  })

  const load = useCallback(() => {
    api
      .get<Deal[]>(`/deals${qs(filters)}`)
      .then(setDeals)
      .catch((e) => setError(e.message))
  }, [filters])

  useEffect(() => { load() }, [load])
  useEffect(() => { api.get<User[]>('/settings/users').then(setUsers).catch(() => setUsers([])) }, [])

  async function move(deal: Deal, stage: string, lost_reason?: string) {
    if (deal.stage === stage) return
    if (stage === 'LOST' && !lost_reason) {
      setLostTarget(deal)
      return
    }
    try {
      await api.patch(`/deals/${deal.id}`, { stage, lost_reason: lost_reason ?? null })
      setLostTarget(null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '단계 이동 실패')
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold text-slate-800">파이프라인</h1>

      <Card>
        <div className="grid grid-cols-4 gap-3 text-sm">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">담당자</span>
            <select className={inputClass} value={filters.owner_id} onChange={(e) => setFilters({ ...filters, owner_id: e.target.value })}>
              <option value="">전체</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">상품</span>
            <select className={inputClass} value={filters.product_code} onChange={(e) => setFilters({ ...filters, product_code: e.target.value })}>
              <option value="">전체</option>
              {meta?.products.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">최소 금액</span>
            <input type="number" className={inputClass} value={filters.amount_min} onChange={(e) => setFilters({ ...filters, amount_min: e.target.value })} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">최대 금액</span>
            <input type="number" className={inputClass} value={filters.amount_max} onChange={(e) => setFilters({ ...filters, amount_max: e.target.value })} />
          </label>
        </div>
      </Card>

      <ErrorText>{error}</ErrorText>

      <div className="flex gap-3 overflow-x-auto pb-4">
        {STAGES.map((stage) => {
          const items = deals.filter((d) => d.stage === stage)
          const sum = items.reduce((s, d) => s + (d.amount ?? 0), 0)
          const isCollapsed = collapsed.has(stage)
          return (
            <div
              key={stage}
              className={`shrink-0 rounded-lg bg-slate-100 p-2 ${isCollapsed ? 'w-32' : 'w-64'}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => dragged && move(dragged, stage)}
            >
              <header className="mb-2 flex items-center justify-between px-1">
                <span className="text-sm font-semibold text-slate-700">{label('deal_stages', stage)}</span>
                {COLLAPSIBLE.has(stage) && (
                  <button
                    className="text-xs text-slate-500"
                    onClick={() => {
                      const next = new Set(collapsed)
                      isCollapsed ? next.delete(stage) : next.add(stage)
                      setCollapsed(next)
                    }}
                  >
                    {isCollapsed ? '펼치기' : '접기'}
                  </button>
                )}
              </header>
              <p className="mb-2 px-1 text-xs text-slate-500">{items.length}건 · {formatMoney(sum)}</p>

              {!isCollapsed && (
                <div className="space-y-2">
                  {items.map((d) => {
                    const overdue = d.next_action_at && new Date(d.next_action_at) < new Date()
                    return (
                      <article
                        key={d.id}
                        draggable
                        onDragStart={() => setDragged(d)}
                        onDragEnd={() => setDragged(null)}
                        className="cursor-grab rounded border border-slate-200 bg-white p-2 text-sm shadow-sm active:cursor-grabbing"
                      >
                        <Link to={`/leads/${d.lead_id}`} className="font-medium text-slate-700 hover:underline">
                          {d.lead_name}
                        </Link>
                        <div className="mt-1 flex items-center justify-between">
                          <Badge tone="blue">{label('products', d.product_code)}</Badge>
                          <span className="text-xs font-medium">{formatMoney(d.amount)}</span>
                        </div>
                        <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                          <span>{d.probability ?? '-'}%</span>
                          <span className="rounded-full bg-slate-200 px-1.5">{d.owner_name ?? '-'}</span>
                        </div>
                        {d.next_action_at && (
                          <p className={`mt-1 text-xs ${overdue ? 'font-medium text-rose-600' : 'text-slate-500'}`}>
                            차기 {formatDate(d.next_action_at)}
                          </p>
                        )}
                      </article>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {lostTarget && (
        <LostReasonModal
          onClose={() => setLostTarget(null)}
          onSubmit={(reason) => move(lostTarget, 'LOST', reason)}
        />
      )}
    </div>
  )
}

function LostReasonModal({ onClose, onSubmit }: { onClose: () => void; onSubmit: (r: string) => void }) {
  const { meta } = useAuth()
  const [reason, setReason] = useState('LOST_NO_BUDGET')
  return (
    <Modal title="실패 사유 선택" onClose={onClose}>
      <select className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)}>
        {meta?.lost_reasons.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
      </select>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>취소</Button>
        <Button variant="danger" onClick={() => onSubmit(reason)}>실패로 이동</Button>
      </div>
    </Modal>
  )
}
