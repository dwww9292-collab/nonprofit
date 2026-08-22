import { useEffect, useState } from 'react'
import { api, qs } from '../api/client'
import { useLabels } from '../auth'
import { Card, Empty, ErrorText, formatMoney, inputClass } from '../components/ui'
import type { Performance } from '../types'

export default function PerformancePage() {
  const label = useLabels()
  const now = new Date()
  const [period, setPeriod] = useState<'month' | 'quarter'>('month')
  const [year, setYear] = useState(now.getFullYear())
  const [unit, setUnit] = useState(now.getMonth() + 1)
  const [data, setData] = useState<Performance | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<Performance>(`/performance${qs({ period, year, unit })}`)
      .then(setData)
      .catch((e) => setError(e.message))
  }, [period, year, unit])

  const units = period === 'month' ? Array.from({ length: 12 }, (_, i) => i + 1) : [1, 2, 3, 4]

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold text-slate-800">실적</h1>

      <Card>
        <div className="flex gap-3">
          <select
            className={`${inputClass} w-28`}
            value={period}
            onChange={(e) => {
              const p = e.target.value as 'month' | 'quarter'
              setPeriod(p)
              setUnit(p === 'month' ? now.getMonth() + 1 : Math.floor(now.getMonth() / 3) + 1)
            }}
          >
            <option value="month">월별</option>
            <option value="quarter">분기별</option>
          </select>
          <select className={`${inputClass} w-28`} value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[now.getFullYear(), now.getFullYear() - 1, now.getFullYear() - 2].map((y) => (
              <option key={y} value={y}>{y}년</option>
            ))}
          </select>
          <select className={`${inputClass} w-28`} value={unit} onChange={(e) => setUnit(Number(e.target.value))}>
            {units.map((u) => <option key={u} value={u}>{period === 'month' ? `${u}월` : `${u}분기`}</option>)}
          </select>
        </div>
      </Card>

      <ErrorText>{error}</ErrorText>

      <Card title={`영업사원별 실적 (${data?.period_label ?? ''})`}>
        {!data || data.rows.length === 0 ? (
          <Empty>표시할 실적이 없습니다.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2">담당자</th>
                <th className="py-2 text-right">배정 리드</th>
                <th className="py-2 text-right">접촉</th>
                <th className="py-2 text-right">접촉 전환율</th>
                <th className="py-2 text-right">미팅</th>
                <th className="py-2 text-right">제안</th>
                <th className="py-2 text-right">수주 건수</th>
                <th className="py-2 text-right">수주 금액</th>
                <th className="py-2 text-right">평균 첫접촉</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.user_id} className="border-b border-slate-50">
                  <td className="py-2 font-medium text-slate-700">{r.name}</td>
                  <td className="py-2 text-right">{r.assigned_leads}</td>
                  <td className="py-2 text-right">{r.contacted_leads}</td>
                  <td className="py-2 text-right">{r.contact_rate}%</td>
                  <td className="py-2 text-right">{r.meetings}</td>
                  <td className="py-2 text-right">{r.proposals}</td>
                  <td className="py-2 text-right font-medium">{r.won_count}</td>
                  <td className="py-2 text-right font-medium">{formatMoney(r.won_amount)}</td>
                  <td className="py-2 text-right text-xs text-slate-500">
                    {r.avg_first_contact_hours === null ? '-' : `${r.avg_first_contact_hours}시간`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="상품별 수주 요약">
        {!data || data.product_summary.length === 0 ? (
          <Empty>해당 기간 수주가 없습니다.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2">상품</th>
                <th className="py-2 text-right">건수</th>
                <th className="py-2 text-right">금액</th>
              </tr>
            </thead>
            <tbody>
              {data.product_summary.map((p) => (
                <tr key={p.product_code} className="border-b border-slate-50">
                  <td className="py-2">{label('products', p.product_code)}</td>
                  <td className="py-2 text-right">{p.count}</td>
                  <td className="py-2 text-right font-medium">{formatMoney(p.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
