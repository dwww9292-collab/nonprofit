import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth'
import { Button, ErrorText, Field, inputClass } from '../components/ui'

export default function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <form onSubmit={submit} className="w-[380px] space-y-4 rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <div>
          <h1 className="text-xl font-bold text-slate-800">NPO Sales Radar</h1>
          <p className="mt-1 text-sm text-slate-500">신규 비영리기구 리드 발굴 · 영업 파이프라인</p>
        </div>
        <Field label="이메일">
          <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </Field>
        <Field label="비밀번호" hint="5회 연속 실패 시 5분간 잠깁니다.">
          <input className={inputClass} type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <ErrorText>{error}</ErrorText>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? '로그인 중…' : '로그인'}
        </Button>
      </form>
    </div>
  )
}
