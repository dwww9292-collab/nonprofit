import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, qs } from '../api/client'
import { useAuth, useLabels } from '../auth'
import { Badge, Button, Card, Empty, ErrorText, GradeBadge, Modal, formatDate, inputClass } from '../components/ui'
import ManualLeadForm from '../components/ManualLeadForm'
import type { Lead, Page, User } from '../types'

const GRADES = ['A', 'B', 'C', 'D']
const PAGE_SIZE = 50

export default function LeadsPage() {
  const { can, meta } = useAuth()
  const label = useLabels()
  const [params, setParams] = useSearchParams()
  const managerUp = can('ADMIN', 'MANAGER')

  const [data, setData] = useState<Page<Lead> | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [error, setError] = useState('')
  const [showManual, setShowManual] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignee, setAssignee] = useState('')

  const get = (k: string) => params.get(k) ?? ''
  const getAll = (k: string) => params.getAll(k)
  const page = Number(get('page') || 1)

  const setParam = useCallback(
    (key: string, value: string | string[] | boolean) => {
      const next = new URLSearchParams(params)
      next.delete(key)
      if (Array.isArray(value)) value.forEach((v) => next.append(key, v))
      else if (value === true) next.set(key, 'true')
      else if (value) next.set(key, String(value))
      if (key !== 'page') next.delete('page')
      setParams(next)
    },
    [params, setParams],
  )

  const query = qs({
    grade: getAll('grade'),
    status: getAll('status'),
    org_type: getAll('org_type'),
    region_code: get('region_code'),
    source_code: get('source_code'),
    assignee_id: get('assignee_id'),
    unassigned: get('unassigned') === 'true',
    collected_from: get('collected_from'),
    collected_to: get('collected_to'),
    include_customers: get('include_customers') === 'true',
    only_possible_dup: get('only_possible_dup') === 'true',
    q: get('q'),
    sort: get('sort') || 'score',
    order: get('order') || 'desc',
    page,
    size: PAGE_SIZE,
  })

  const reload = useCallback(() => {
    api.get<Page<Lead>>(`/leads${query}`).then(setData).catch((e) => setError(e.message))
  }, [query])

  useEffect(() => {
    reload()
    setSelected(new Set())
  }, [reload])

  useEffect(() => {
    api.get<User[]>('/settings/users').then(setUsers).catch(() => setUsers([]))
  }, [])

  function toggleMulti(key: string, value: string) {
    const cur = getAll(key)
    setParam(key, cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value])
  }

  function sortBy(col: string) {
    const isSame = (get('sort') || 'score') === col
    const next = new URLSearchParams(params)
    next.set('sort', col)
    next.set('order', isSame && (get('order') || 'desc') === 'desc' ? 'asc' : 'desc')
    setParams(next)
  }

  async function bulkAssign() {
    try {
      await api.post('/leads/assign', { lead_ids: [...selected], assignee_id: Number(assignee) })
      setAssignOpen(false)
      setAssignee('')
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '배정에 실패했습니다.')
    }
  }

  async function bulkStatus(status: string) {
    const lost_reason = status === 'LOST' ? prompt('실패 사유 코드 (예: LOST_NO_BUDGET)') : null
    if (status === 'LOST' && !lost_reason) return
    try {
      await api.post('/leads/bulk-status', { lead_ids: [...selected], status, lost_reason })
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '상태 변경에 실패했습니다.')
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-slate-800">
          리드 <span className="text-sm font-normal text-slate-500">{data?.total ?? 0}건</span>
        </h1>
        <div className="flex gap-2">
          <Button onClick={() => setShowManual(true)}>수기입력 +</Button>
          {managerUp && (
            <Button
              variant="secondary"
              onClick={() => api.download(`/leads/export${query.replace(/[?&](page|size)=\d+/g, '')}`, 'leads.csv')}
            >
              CSV 내보내기
            </Button>
          )}
        </div>
      </div>

      <Card>
        <div className="grid grid-cols-4 gap-3 text-sm">
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">등급</p>
            <div className="flex gap-1">
              {GRADES.map((g) => (
                <button
                  key={g}
                  onClick={() => toggleMulti('grade', g)}
                  className={`rounded px-2 py-1 text-xs ring-1 ${
                    getAll('grade').includes(g) ? 'bg-slate-800 text-white ring-slate-800' : 'bg-white text-slate-600 ring-slate-300'
                  }`}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">상태</p>
            <select className={inputClass} value="" onChange={(e) => e.target.value && toggleMulti('status', e.target.value)}>
              <option value="">＋ 상태 추가</option>
              {meta?.lead_statuses.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
            <div className="mt-1 flex flex-wrap gap-1">
              {getAll('status').map((s) => (
                <button key={s} onClick={() => toggleMulti('status', s)} className="rounded bg-slate-200 px-1.5 py-0.5 text-xs">
                  {label('lead_statuses', s)} ✕
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">유형</p>
            <select className={inputClass} value="" onChange={(e) => e.target.value && toggleMulti('org_type', e.target.value)}>
              <option value="">＋ 유형 추가</option>
              {meta?.org_types.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
            <div className="mt-1 flex flex-wrap gap-1">
              {getAll('org_type').map((s) => (
                <button key={s} onClick={() => toggleMulti('org_type', s)} className="rounded bg-slate-200 px-1.5 py-0.5 text-xs">
                  {label('org_types', s)} ✕
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">지역(시도)</p>
            <select className={inputClass} value={get('region_code')} onChange={(e) => setParam('region_code', e.target.value)}>
              <option value="">전체</option>
              {meta?.regions.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">담당자</p>
            <select
              className={inputClass}
              value={get('unassigned') === 'true' ? 'UNASSIGNED' : get('assignee_id')}
              onChange={(e) => {
                if (e.target.value === 'UNASSIGNED') {
                  setParam('assignee_id', '')
                  setParam('unassigned', true)
                } else {
                  setParam('unassigned', '')
                  setParam('assignee_id', e.target.value)
                }
              }}
            >
              <option value="">전체</option>
              <option value="UNASSIGNED">미배정</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">수집일</p>
            <div className="flex gap-1">
              <input type="date" className={inputClass} value={get('collected_from')} onChange={(e) => setParam('collected_from', e.target.value)} />
              <input type="date" className={inputClass} value={get('collected_to')} onChange={(e) => setParam('collected_to', e.target.value)} />
            </div>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">검색</p>
            <input
              className={inputClass}
              placeholder="법인명·주소"
              defaultValue={get('q')}
              onKeyDown={(e) => e.key === 'Enter' && setParam('q', (e.target as HTMLInputElement).value)}
            />
          </div>
          <div className="flex items-end gap-4 text-xs text-slate-600">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={get('include_customers') === 'true'} onChange={(e) => setParam('include_customers', e.target.checked)} />
              기고객 포함
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={get('only_possible_dup') === 'true'} onChange={(e) => setParam('only_possible_dup', e.target.checked)} />
              중복의심만
            </label>
          </div>
        </div>
      </Card>

      <ErrorText>{error}</ErrorText>

      {managerUp && selected.size > 0 && (
        <div className="flex items-center gap-3 rounded bg-slate-800 px-4 py-2 text-sm text-white">
          <span>{selected.size}건 선택됨</span>
          <button onClick={() => setAssignOpen(true)} className="rounded bg-white/20 px-2 py-1">일괄 배정</button>
          <button onClick={() => bulkStatus('ON_HOLD')} className="rounded bg-white/20 px-2 py-1">보류로 변경</button>
          <button onClick={() => bulkStatus('LOST')} className="rounded bg-white/20 px-2 py-1">실패 처리</button>
          <button onClick={() => setSelected(new Set())} className="ml-auto underline">선택 해제</button>
        </div>
      )}

      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              {managerUp && (
                <th className="w-8 py-2">
                  <input
                    type="checkbox"
                    checked={!!data?.items.length && selected.size === data.items.length}
                    onChange={(e) => setSelected(e.target.checked ? new Set(data?.items.map((i) => i.id)) : new Set())}
                  />
                </th>
              )}
              <th className="cursor-pointer py-2" onClick={() => sortBy('grade')}>등급</th>
              <th className="cursor-pointer py-2" onClick={() => sortBy('org_name')}>법인명</th>
              <th className="py-2">유형</th>
              <th className="py-2">지역</th>
              <th className="cursor-pointer py-2" onClick={() => sortBy('established_at')}>설립·지정일</th>
              <th className="py-2">단계신호</th>
              <th className="cursor-pointer py-2 text-right" onClick={() => sortBy('score')}>점수</th>
              <th className="cursor-pointer py-2" onClick={() => sortBy('status')}>상태</th>
              <th className="py-2">담당자</th>
              <th className="py-2">소스</th>
              <th className="cursor-pointer py-2" onClick={() => sortBy('collected_at')}>수집일</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((l) => (
              <tr key={l.id} className="border-b border-slate-50 hover:bg-slate-50">
                {managerUp && (
                  <td className="py-2">
                    <input
                      type="checkbox"
                      checked={selected.has(l.id)}
                      onChange={(e) => {
                        const next = new Set(selected)
                        e.target.checked ? next.add(l.id) : next.delete(l.id)
                        setSelected(next)
                      }}
                    />
                  </td>
                )}
                <td className="py-2"><GradeBadge grade={l.grade} /></td>
                <td className="py-2">
                  <Link to={`/leads/${l.id}`} className="font-medium text-slate-700 hover:underline">{l.org_name}</Link>
                  <span className="ml-1 space-x-1">
                    {l.is_existing_customer && <Badge tone="green">기고객</Badge>}
                    {l.possible_dup_lead_id && <Badge tone="amber">중복의심</Badge>}
                    {l.possible_revoked && <Badge tone="red">지정취소?</Badge>}
                  </span>
                </td>
                <td className="py-2 text-xs text-slate-600">{label('org_types', l.org_type)}</td>
                <td className="py-2 text-xs text-slate-600">
                  {label('regions', l.region_code)} {l.district ?? ''}
                </td>
                <td className="py-2 text-xs text-slate-600">
                  {formatDate(l.designated_at ?? l.established_at)}
                </td>
                <td className="py-2"><Badge tone="blue">{label('stage_signals', l.stage_signal)}</Badge></td>
                <td className="py-2 text-right font-medium">{l.score}</td>
                <td className="py-2 text-xs">{label('lead_statuses', l.status)}</td>
                <td className="py-2 text-xs text-slate-600">{l.assignee_name ?? '-'}</td>
                <td className="py-2 text-xs text-slate-500">{l.source_code?.replace('SRC_', '')}</td>
                <td className="py-2 text-xs text-slate-500">{formatDate(l.collected_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.items.length === 0 && <Empty>조건에 맞는 리드가 없습니다.</Empty>}

        {totalPages > 1 && (
          <div className="mt-3 flex items-center justify-center gap-2 text-sm">
            <Button variant="ghost" disabled={page <= 1} onClick={() => setParam('page', String(page - 1))}>이전</Button>
            <span className="text-slate-500">{page} / {totalPages}</span>
            <Button variant="ghost" disabled={page >= totalPages} onClick={() => setParam('page', String(page + 1))}>다음</Button>
          </div>
        )}
      </Card>

      {showManual && (
        <ManualLeadForm
          onClose={() => setShowManual(false)}
          onCreated={() => {
            setShowManual(false)
            reload()
          }}
        />
      )}

      {assignOpen && (
        <Modal title={`${selected.size}건 일괄 배정`} onClose={() => setAssignOpen(false)}>
          <select className={inputClass} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">담당자 선택</option>
            {users.filter((u) => u.is_active).map((u) => (
              <option key={u.id} value={u.id}>{u.name} ({u.role})</option>
            ))}
          </select>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setAssignOpen(false)}>취소</Button>
            <Button disabled={!assignee} onClick={bulkAssign}>배정</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
