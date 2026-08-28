import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, setActorUsername, type SessionUser } from '../api'

type SessionState = {
  user: SessionUser | null
  users: SessionUser[]
  setUser: (username: string) => Promise<void>
}

const SessionContext = createContext<SessionState | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<SessionUser | null>(null)
  const [users, setUsers] = useState<SessionUser[]>([])

  useEffect(() => {
    api
      .session()
      .then((s) => {
        setUserState(s.user)
        setUsers(s.users)
        setActorUsername(s.user.username)
      })
      .catch(() => undefined)
  }, [])

  const setUser = useCallback(async (username: string) => {
    const s = await api.switchSession(username)
    setUserState(s.user)
    setUsers(s.users)
    setActorUsername(s.user.username)
  }, [])

  const value = useMemo(() => ({ user, users, setUser }), [user, users, setUser])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used within SessionProvider')
  return ctx
}
