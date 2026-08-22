import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, tokenStore } from './api/client'
import type { EnumMeta, Role, User } from './types'

interface AuthState {
  user: User | null
  meta: EnumMeta | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  can: (...roles: Role[]) => boolean
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [meta, setMeta] = useState<EnumMeta | null>(null)
  const [loading, setLoading] = useState(true)

  const loadSession = useCallback(async () => {
    if (!tokenStore.get()) {
      setLoading(false)
      return
    }
    try {
      const [me, enums] = await Promise.all([api.get<User>('/auth/me'), api.get<EnumMeta>('/meta/enums')])
      setUser(me)
      setMeta(enums)
    } catch {
      tokenStore.clear()
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSession()
  }, [loadSession])

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.post<{ access_token: string; user: User }>('/auth/login', { email, password })
    tokenStore.set(res.access_token)
    setUser(res.user)
    setMeta(await api.get<EnumMeta>('/meta/enums'))
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    setMeta(null)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      meta,
      loading,
      login,
      logout,
      can: (...roles: Role[]) => !!user && roles.includes(user.role),
    }),
    [user, meta, loading, login, logout],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('AuthProvider 밖에서 useAuth를 사용했습니다.')
  return ctx
}

/** enum 코드 → 표시명 */
export function useLabels() {
  const { meta } = useAuth()
  return useCallback(
    (group: keyof EnumMeta, code: string | null | undefined): string => {
      if (!code) return '-'
      const list = meta?.[group]
      if (!Array.isArray(list)) return code
      const hit = (list as { code: string; label: string }[]).find((o) => o.code === code)
      return hit?.label ?? code
    },
    [meta],
  )
}
