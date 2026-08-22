import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import DashboardPage from './pages/Dashboard'
import IngestPage from './pages/Ingest'
import LeadDetailPage from './pages/LeadDetail'
import LeadsPage from './pages/Leads'
import LoginPage from './pages/Login'
import PerformancePage from './pages/Performance'
import PipelinePage from './pages/Pipeline'
import SettingsPage from './pages/Settings'

const NAV = [
  { to: '/', label: '대시보드', end: true },
  { to: '/leads', label: '리드' },
  { to: '/pipeline', label: '파이프라인' },
  { to: '/ingest', label: '데이터 업로드', managerUp: true },
  { to: '/performance', label: '실적' },
  { to: '/settings', label: '설정', managerUp: true },
]

function Shell() {
  const { user, logout, can } = useAuth()
  const navigate = useNavigate()
  const managerUp = can('ADMIN', 'MANAGER')

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-4">
          <p className="text-base font-bold text-slate-800">NPO Sales Radar</p>
          <p className="text-xs text-slate-500">아이원소프트뱅크</p>
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {NAV.filter((n) => !n.managerUp || managerUp).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${
                  isActive ? 'bg-slate-800 font-medium text-white' : 'text-slate-600 hover:bg-slate-100'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-3 text-xs">
          <p className="font-medium text-slate-700">{user?.name}</p>
          <p className="text-slate-500">
            {user?.role === 'ADMIN' ? '관리자' : user?.role === 'MANAGER' ? '팀장' : '영업사원'}
          </p>
          <button
            onClick={() => {
              logout()
              navigate('/login')
            }}
            className="mt-2 text-slate-500 underline hover:text-slate-700"
          >
            로그아웃
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-x-auto p-6">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/leads" element={<LeadsPage />} />
          <Route path="/leads/:id" element={<LeadDetailPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/performance" element={<PerformancePage />} />
          {managerUp && <Route path="/ingest" element={<IngestPage />} />}
          {managerUp && <Route path="/settings" element={<SettingsPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="p-10 text-sm text-slate-500">불러오는 중…</div>
  }

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="*" element={user ? <Shell /> : <Navigate to="/login" replace />} />
    </Routes>
  )
}
