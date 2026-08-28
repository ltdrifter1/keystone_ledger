import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, type Entity } from '../api'

const PERIOD_KEY = 'keystone.period'
const ENTITY_KEY = 'keystone.entity_id'

export type EngagementState = {
  year: number
  month: number
  label: string
  entityId: string
  entityCode: string | null
  entityName: string | null
  entityCurrency: string
  entities: Entity[]
  setPeriod: (year: number, month: number) => void
  setYear: (year: number) => void
  setMonth: (month: number) => void
  setEntityId: (id: string) => void
}

const EngagementContext = createContext<EngagementState | null>(null)

function readPeriod(): { year: number; month: number } {
  // WBC fiscal year ends 31 July — default the close to last year's books.
  const fallback = { year: 2026, month: 7 }
  try {
    const raw = localStorage.getItem(PERIOD_KEY)
    if (!raw) {
      const legacy = localStorage.getItem('keystone.close.period')
      if (legacy) {
        const parsed = JSON.parse(legacy) as { year?: string; month?: string }
        return {
          year: Number(parsed.year) || fallback.year,
          month: Number(parsed.month) || fallback.month,
        }
      }
      return fallback
    }
    const parsed = JSON.parse(raw) as { year?: number; month?: number }
    return {
      year: Number(parsed.year) || fallback.year,
      month: Math.min(12, Math.max(1, Number(parsed.month) || fallback.month)),
    }
  } catch {
    return fallback
  }
}

function readEntityId(): string {
  try {
    return localStorage.getItem(ENTITY_KEY) || ''
  } catch {
    return ''
  }
}

export function EngagementProvider({ children }: { children: ReactNode }) {
  const initial = readPeriod()
  const [year, setYearState] = useState(initial.year)
  const [month, setMonthState] = useState(initial.month)
  const [entityId, setEntityIdState] = useState(readEntityId)
  const [entities, setEntities] = useState<Entity[]>([])

  useEffect(() => {
    api.entities().then((list) => {
      setEntities(list)
      setEntityIdState((current) => {
        if (current && list.some((e) => String(e.id) === current)) return current
        const can = list.find((e) => e.code === 'CAN')
        const next = can ? String(can.id) : list[0] ? String(list[0].id) : ''
        return next
      })
    })
  }, [])

  useEffect(() => {
    localStorage.setItem(PERIOD_KEY, JSON.stringify({ year, month }))
    localStorage.setItem(
      'keystone.close.period',
      JSON.stringify({ year: String(year), month: String(month) }),
    )
  }, [year, month])

  useEffect(() => {
    if (entityId) localStorage.setItem(ENTITY_KEY, entityId)
  }, [entityId])

  const setPeriod = useCallback((y: number, m: number) => {
    setYearState(y)
    setMonthState(Math.min(12, Math.max(1, m)))
  }, [])
  const setYear = useCallback((y: number) => setYearState(y), [])
  const setMonth = useCallback((m: number) => setMonthState(Math.min(12, Math.max(1, m))), [])
  const setEntityId = useCallback((id: string) => setEntityIdState(id), [])

  const entityCode = useMemo(() => {
    const match = entities.find((e) => String(e.id) === entityId)
    return match?.code ?? null
  }, [entities, entityId])

  const entityName = useMemo(() => {
    const match = entities.find((e) => String(e.id) === entityId)
    return match?.name ?? entityCode
  }, [entities, entityId, entityCode])

  const entityCurrency = useMemo(() => {
    const match = entities.find((e) => String(e.id) === entityId)
    return match?.functional_currency || 'CAD'
  }, [entities, entityId])

  const value = useMemo<EngagementState>(
    () => ({
      year,
      month,
      label: `${year}-${String(month).padStart(2, '0')}`,
      entityId,
      entityCode,
      entityName,
      entityCurrency,
      entities,
      setPeriod,
      setYear,
      setMonth,
      setEntityId,
    }),
    [year, month, entityId, entityCode, entityName, entityCurrency, entities, setPeriod, setYear, setMonth, setEntityId],
  )

  return <EngagementContext.Provider value={value}>{children}</EngagementContext.Provider>
}

/** @deprecated use useEngagement — kept for existing pages */
export function usePeriod() {
  const ctx = useContext(EngagementContext)
  if (!ctx) throw new Error('usePeriod must be used within EngagementProvider')
  return ctx
}

export function useEngagement() {
  const ctx = useContext(EngagementContext)
  if (!ctx) throw new Error('useEngagement must be used within EngagementProvider')
  return ctx
}
