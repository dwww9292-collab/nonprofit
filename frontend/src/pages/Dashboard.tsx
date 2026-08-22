import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth, useLabels } from '../auth'
import { Card, Empty, GradeBadge, formatDate, formatMoney } from '../components/ui'
import type { Dashboard } from '../types'

const GRADE_COLOR: Record<string, string> = {
  A: 'bg-rose-400',
  B: 'bg-amber-400',
  C: 'bg-sky-400',
  D: 'bg-slate-300',
}

const SOURCE_COLOR = ['bg-slate-700', 'bg-sky-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-400', 'bg-violet-500']

export default function DashboardPage() {
  const { can } = useAuth()
  const label = useLabels()
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<Dashboard>('/dashboard').then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="text-sm text-rose-600">{error}</p>
  if (!data) return <p className="text-sm text-slate-500">불러오는 중…</p>

  const weeks = [...new Set(data.weekly_inflow.map((w) => w.week))].sort()
  const sources = [...new Set(data.weekly_inflow.map((w) => w.source_code))]
  const weekTotals = weeks.map((w) =>
    data.weekly_inflow.filter((x) => x.week === w).reduce((s, x) => s + x.count, 0),
  )
  const maxWeek = Math.max(1, ...weekTotals)
  const gradeMax = Math.max(1, ...Object.values(data.grade_distribution))
  const pipeMax = Math.max(1, ...data.pipeline_summary.map((s) => s.count))

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold text-slate-800">대시보드</h1>

      <div className="grid grid-cols-2 gap-4">
        <Card
          title={
            <span className="flex items-center gap-2">
              즉시 배정 필요
              <span className="rounded bg-rose-600 px-1.5 py-0.5 text-xs font-bold text-white">
                {data.urgent_unassigned_count}
              </span>
            </span>
          }
          action={<Link to="/leads?grade=A&unassigned=true" className="text-xs text-slate-500 underline">전체 보기</Link>}
        >
          {data.urgent_unassigned.length === 0 ? (
            <Empty>A등급 미배정 리드가 없습니다.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.urgent_unassigned.map((l) => (
                <li key={l.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <GradeBadge grade={l.grade} score={l.score} />
                    <Link to={`/leads/${l.id}`} className="font-medium text-slate-700 hover:underline">
                      {l.org_name}
                    </Link>
                  </span>
                  <span className="flex items-center gap-3 text-xs text-slate-500">
                    {formatDate(l.collected_at)}
                    {can('ADMIN', 'MANAGER') && (
                      <Link to={`/leads/${l.id}`} className="rounded bg-slate-800 px-2 py-1 text-white">배정</Link>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title={
            <span className="flex items-center gap-2">
              장기 미접촉 경고
              <span className="rounded bg-amber-500 px-1.5 py-0.5 text-xs font-bold text-white">
                {data.stale_assigned_count}
              </span>
            </span>
          }
        >
          {data.stale_assigned.length === 0 ? (
            <Empty>배정 후 7일 넘게 방치된 리드가 없습니다.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.stale_assigned.map((l) => (
                <li key={l.id} className="flex items-center justify-between py-2 text-sm">
                  <Link to={`/leads/${l.id}`} className="font-medium text-slate-700 hover:underline">
                    {l.org_name}
                  </Link>
                  <span className="text-xs text-slate-500">
                    {l.assignee_name} · 배정 {l.days_since_assigned}일 경과
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Card title="신규 리드 유입 추이 (최근 12주)" className="col-span-2">
          {weeks.length === 0 ? (
            <Empty>표시할 유입 데이터가 없습니다.</Empty>
          ) : (
            <>
              <div className="flex gap-1">
                {weeks.map((w) => {
                  const total = data.weekly_inflow.filter((x) => x.week === w).reduce((s, x) => s + x.count, 0)
                  return (
                    <div key={w} className="flex flex-1 flex-col items-center gap-1" title={`${w}: ${total}건`}>
                      {/* h-36은 고정 높이 — 자식의 % 높이가 해석되려면 부모 높이가 확정이어야 한다 */}
                      <div className="flex h-36 w-full flex-col justify-end">
                        <div className="flex w-full flex-col-reverse" style={{ height: `${(total / maxWeek) * 100}%` }}>
                          {sources.map((s) => {
                            const c = data.weekly_inflow.find((x) => x.week === w && x.source_code === s)?.count ?? 0
                            if (!c) return null
                            return (
                              <div
                                key={s}
                                className={SOURCE_COLOR[sources.indexOf(s) % SOURCE_COLOR.length]}
                                style={{ height: `${(c / total) * 100}%` }}
                              />
                            )
                          })}
                        </div>
                      </div>
                      <span className="text-[10px] text-slate-400">{w.slice(-2)}</span>
                    </div>
                  )
                })}
              </div>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
                {sources.map((s, i) => (
                  <span key={s} className="flex items-center gap-1">
                    <span className={`inline-block h-2 w-2 rounded-sm ${SOURCE_COLOR[i % SOURCE_COLOR.length]}`} />
                    {s.replace('SRC_', '')}
                  </span>
                ))}
              </div>
            </>
          )}
        </Card>

        <Card title="등급 분포">
          <ul className="space-y-2">
            {(['A', 'B', 'C', 'D'] as const).map((g) => (
              <li key={g} className="flex items-center gap-2 text-sm">
                <span className="w-4 font-bold text-slate-600">{g}</span>
                <div className="h-4 flex-1 rounded bg-slate-100">
                  <div
                    className={`h-4 rounded ${GRADE_COLOR[g]}`}
                    style={{ width: `${((data.grade_distribution[g] ?? 0) / gradeMax) * 100}%` }}
                  />
                </div>
                <span className="w-8 text-right text-xs text-slate-500">{data.grade_distribution[g] ?? 0}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card title="파이프라인 요약">
          <ul className="space-y-2">
            {data.pipeline_summary.map((s) => (
              <li key={s.stage} className="flex items-center gap-2 text-sm">
                <span className="w-14 text-xs text-slate-600">{label('deal_stages', s.stage)}</span>
                <div className="h-5 flex-1 rounded bg-slate-100">
                  <div className="h-5 rounded bg-slate-600" style={{ width: `${(s.count / pipeMax) * 100}%` }} />
                </div>
                <span className="w-24 text-right text-xs text-slate-500">
                  {s.count}건 · {formatMoney(s.amount)}
                </span>
              </li>
            ))}
          </ul>
        </Card>

        <Card title={`이번 분기 수주 (${data.quarter_label})`}>
          {data.quarter_won.length === 0 ? (
            <Empty>이번 분기 확정된 수주가 없습니다.</Empty>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                  <th className="py-1">상품</th>
                  <th className="py-1 text-right">건수</th>
                  <th className="py-1 text-right">금액</th>
                </tr>
              </thead>
              <tbody>
                {data.quarter_won.map((p) => (
                  <tr key={p.product_code} className="border-b border-slate-50">
                    <td className="py-1.5">{label('products', p.product_code)}</td>
                    <td className="py-1.5 text-right">{p.count}</td>
                    <td className="py-1.5 text-right font-medium">{formatMoney(p.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  )
}
