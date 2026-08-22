import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Badge, Button, Card, ErrorText, Field, Modal, inputClass } from '../components/ui'
import type { ScoringSetting, Source, User } from '../types'

type Tab = 'scoring' | 'users' | 'sources' | 'assignment'

const TABS: { key: Tab; label: string }[] = [
  { key: 'scoring', label: '스코어링 가중치' },
  { key: 'users', label: '사용자 관리' },
  { key: 'sources', label: '소스 관리' },
  { key: 'assignment', label: '배정 규칙' },
]

export default function SettingsPage() {
  const { can } = useAuth()
  const [tab, setTab] = useState<Tab>('scoring')
  const isAdmin = can('ADMIN')

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-bold text-slate-800">설정</h1>
        {!isAdmin && <Badge tone="amber">조회 전용 (변경은 ADMIN만 가능)</Badge>}
      </div>

      <nav className="flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm ${
              tab === t.key ? 'border-b-2 border-slate-800 font-medium text-slate-800' : 'text-slate-500'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'scoring' && <ScoringTab isAdmin={isAdmin} />}
      {tab === 'users' && <UsersTab isAdmin={isAdmin} />}
      {tab === 'sources' && <SourcesTab isAdmin={isAdmin} />}
      {tab === 'assignment' && <AssignmentTab isAdmin={isAdmin} />}
    </div>
  )
}

function ScoringTab({ isAdmin }: { isAdmin: boolean }) {
  const [rows, setRows] = useState<ScoringSetting[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api.get<ScoringSetting[]>('/settings/scoring').then(setRows).catch((e) => setError(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function savePoints(rule: ScoringSetting, points: number) {
    try {
      await api.patch(`/settings/scoring/${rule.rule_key}`, { points })
      setMessage(`${rule.rule_key} 배점을 ${points}점으로 저장했습니다. 반영하려면 전체 재계산을 실행하세요.`)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  async function saveCodes(rule: ScoringSetting, raw: string) {
    const codes = raw.split(',').map((c) => c.trim()).filter(Boolean)
    try {
      await api.patch(`/settings/scoring/${rule.rule_key}`, { value_json: { codes } })
      setMessage(`${rule.rule_key} 지역 목록을 저장했습니다.`)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  async function rescore() {
    setBusy(true)
    setMessage('')
    try {
      const res = await api.post<{ updated: number }>('/settings/scoring/rescore')
      setMessage(`${res.updated}건의 리드를 재계산했습니다.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '재계산 실패')
    } finally {
      setBusy(false)
    }
  }

  const groups = [...new Set(rows.map((r) => r.rule_key.split('.')[0]))]

  return (
    <Card
      title="배점 설정 (docs/03-scoring.md v1)"
      action={isAdmin && <Button disabled={busy} onClick={rescore}>{busy ? '재계산 중…' : '전체 재계산 실행'}</Button>}
    >
      <ErrorText>{error}</ErrorText>
      {message && <p className="mb-3 rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</p>}

      {groups.map((g) => (
        <div key={g} className="mb-5">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">{g}</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-1 w-56">rule_key</th>
                <th className="py-1">설명</th>
                <th className="py-1 w-24 text-right">배점</th>
                <th className="py-1 w-64">지역 코드 목록</th>
              </tr>
            </thead>
            <tbody>
              {rows.filter((r) => r.rule_key.startsWith(`${g}.`)).map((r) => (
                <tr key={r.id} className="border-b border-slate-50">
                  <td className="py-1.5 font-mono text-xs">{r.rule_key}</td>
                  <td className="py-1.5 text-xs text-slate-600">{r.description}</td>
                  <td className="py-1.5 text-right">
                    <input
                      type="number"
                      defaultValue={r.points}
                      disabled={!isAdmin}
                      className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-sm disabled:bg-slate-50"
                      onBlur={(e) => Number(e.target.value) !== r.points && savePoints(r, Number(e.target.value))}
                    />
                  </td>
                  <td className="py-1.5">
                    {r.value_json && 'codes' in r.value_json && (
                      <input
                        defaultValue={(r.value_json.codes as string[]).join(', ')}
                        disabled={!isAdmin}
                        className="w-full rounded border border-slate-300 px-2 py-1 text-xs disabled:bg-slate-50"
                        onBlur={(e) => saveCodes(r, e.target.value)}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </Card>
  )
}

function UsersTab({ isAdmin }: { isAdmin: boolean }) {
  const { meta } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState('')
  const [showNew, setShowNew] = useState(false)

  const load = useCallback(() => {
    api.get<User[]>('/settings/users').then(setUsers).catch((e) => setError(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function patch(user: User, body: Record<string, unknown>) {
    try {
      await api.patch(`/settings/users/${user.id}`, body)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  return (
    <Card title="사용자" action={isAdmin && <Button onClick={() => setShowNew(true)}>사용자 추가 +</Button>}>
      <ErrorText>{error}</ErrorText>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th className="py-2">이름</th>
            <th className="py-2">이메일</th>
            <th className="py-2 w-32">롤</th>
            <th className="py-2 w-64">담당 지역 (시도 코드)</th>
            <th className="py-2 w-24">상태</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-slate-50">
              <td className="py-2 font-medium text-slate-700">{u.name}</td>
              <td className="py-2 text-xs text-slate-600">{u.email}</td>
              <td className="py-2">
                <select
                  className={inputClass}
                  value={u.role}
                  disabled={!isAdmin}
                  onChange={(e) => patch(u, { role: e.target.value })}
                >
                  {meta?.roles.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                </select>
              </td>
              <td className="py-2">
                <input
                  className={inputClass}
                  defaultValue={(u.region_codes ?? []).join(', ')}
                  disabled={!isAdmin}
                  placeholder="예: 11, 41"
                  onBlur={(e) =>
                    patch(u, { region_codes: e.target.value.split(',').map((c) => c.trim()).filter(Boolean) })
                  }
                />
              </td>
              <td className="py-2">
                {isAdmin ? (
                  <button
                    className={`rounded px-2 py-1 text-xs ${u.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-600'}`}
                    onClick={() => patch(u, { is_active: !u.is_active })}
                  >
                    {u.is_active ? '활성' : '비활성'}
                  </button>
                ) : (
                  <Badge tone={u.is_active ? 'green' : 'slate'}>{u.is_active ? '활성' : '비활성'}</Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {showNew && <NewUserModal onClose={() => setShowNew(false)} onDone={load} />}
    </Card>
  )
}

function NewUserModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { meta } = useAuth()
  const [form, setForm] = useState({ email: '', password: '', name: '', role: 'SALES', region_codes: '' })
  const [error, setError] = useState('')

  async function submit() {
    try {
      await api.post('/settings/users', {
        ...form,
        region_codes: form.region_codes.split(',').map((c) => c.trim()).filter(Boolean),
      })
      onDone()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '생성 실패')
    }
  }

  return (
    <Modal title="사용자 추가" onClose={onClose}>
      <div className="space-y-3">
        <Field label="이름"><input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="이메일"><input className={inputClass} type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="비밀번호" hint="8자 이상"><input className={inputClass} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        <Field label="롤">
          <select className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {meta?.roles.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="담당 지역" hint="시도 코드를 쉼표로 구분 (예: 11, 41)">
          <input className={inputClass} value={form.region_codes} onChange={(e) => setForm({ ...form, region_codes: e.target.value })} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>취소</Button>
          <Button onClick={submit}>생성</Button>
        </div>
      </div>
    </Modal>
  )
}

function SourcesTab({ isAdmin }: { isAdmin: boolean }) {
  const [sources, setSources] = useState<Source[]>([])
  const [error, setError] = useState('')

  const load = useCallback(() => {
    api.get<Source[]>('/settings/sources').then(setSources).catch((e) => setError(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function patch(s: Source, body: Record<string, unknown>) {
    try {
      await api.patch(`/settings/sources/${s.id}`, body)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  return (
    <Card title="수집 소스">
      <ErrorText>{error}</ErrorText>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th className="py-2">코드</th>
            <th className="py-2">이름</th>
            <th className="py-2 w-28">수집 방식</th>
            <th className="py-2 w-32">공공누리 유형</th>
            <th className="py-2">비고 / 크롤링 검토 메모</th>
            <th className="py-2 w-20">활성</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.id} className="border-b border-slate-50">
              <td className="py-2 font-mono text-xs">{s.code}</td>
              <td className="py-2">{s.name}</td>
              <td className="py-2"><Badge tone={s.collect_method === 'FILE_UPLOAD' ? 'blue' : 'slate'}>{s.collect_method}</Badge></td>
              <td className="py-2">
                <input
                  className={inputClass}
                  defaultValue={s.license_type ?? ''}
                  disabled={!isAdmin}
                  placeholder="KOGL_1 등"
                  onBlur={(e) => e.target.value !== (s.license_type ?? '') && patch(s, { license_type: e.target.value || null })}
                />
              </td>
              <td className="py-2">
                <input
                  className={inputClass}
                  defaultValue={s.crawl_note ?? ''}
                  disabled={!isAdmin}
                  onBlur={(e) => e.target.value !== (s.crawl_note ?? '') && patch(s, { crawl_note: e.target.value || null })}
                />
              </td>
              <td className="py-2">
                {isAdmin ? (
                  <input type="checkbox" checked={s.is_active} onChange={(e) => patch(s, { is_active: e.target.checked })} />
                ) : (
                  <Badge tone={s.is_active ? 'green' : 'slate'}>{s.is_active ? 'ON' : 'OFF'}</Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

function AssignmentTab({ isAdmin }: { isAdmin: boolean }) {
  const [enabled, setEnabled] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    api
      .get<{ key: string; value: Record<string, unknown> }[]>('/settings/app')
      .then((rows) => {
        const hit = rows.find((r) => r.key === 'region_assignment_suggestion')
        setEnabled(hit ? Boolean(hit.value.enabled) : true)
      })
      .catch((e) => setError(e.message))
  }, [])

  async function toggle(next: boolean) {
    try {
      await api.put('/settings/app/region_assignment_suggestion', { enabled: next })
      setEnabled(next)
      setMessage('저장했습니다.')
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    }
  }

  return (
    <Card title="배정 규칙">
      <ErrorText>{error}</ErrorText>
      {message && <p className="mb-3 rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</p>}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={enabled} disabled={!isAdmin} onChange={(e) => toggle(e.target.checked)} />
        지역 기반 배정 제안 사용
      </label>
      <p className="mt-2 text-xs text-slate-500">
        켜면 배정 모달에서 리드의 시도 코드와 담당 지역이 일치하는 사원을 상단에 추천합니다. 자동 배정은 하지 않습니다.
      </p>
    </Card>
  )
}
