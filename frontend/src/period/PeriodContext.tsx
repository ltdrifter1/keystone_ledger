import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

const STORAGE_KEY = 'keystone.period'

export type PeriodState = {
  year: number
  month: number
  label: string
  setPeriod: (year: number, month: number) => void
  setYear: (year: number) => void
  setMonth: (month: number) => void
}

const PeriodContext = createContext<PeriodState | null>(null)

function readStored(): { year: number; month: number } {
  const now = new Date()
  const fallback = { year: now.getFullYear(), month: now.getMonth() + 1 }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      // Migrate legacy close period if present
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
    const year = Number(parsed.year) || fallback.year
    const month = Number(parsed.month) || fallback.month
    return { year, month: Math.min(12, Math.max(1, month)) }
  } catch {
    return fallback
  }
}

export function PeriodProvider({ children }: { children: ReactNode }) {
  const initial = readStored()
  const [year, setYearState] = useState(initial.year)
  const [month, setMonthState] = useState(initial.month)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ year, month }))
    localStorage.setItem('keystone.close.period', JSON.stringify({ year: String(year), month: String(month) }))
  }, [year, month])

  const setPeriod = useCallback((y: number, m: number) => {
    setYearState(y)
    setMonthState(Math.min(12, Math.max(1, m)))
  }, [])

  const setYear = useCallback((y: number) => setYearState(y), [])
  const setMonth = useCallback((m: number) => setMonthState(Math.min(12, Math.max(1, m))), [])

  const value = useMemo<PeriodState>(
    () => ({
      year,
      month,
      label: `${year}-${String(month).padStart(2, '0')}`,
      setPeriod,
      setYear,
      setMonth,
    }),
    [year, month, setPeriod, setYear, setMonth],
  )

  return <PeriodContext.Provider value={value}>{children}</PeriodContext.Provider>
}

export function usePeriod() {
  const ctx = useContext(PeriodContext)
  if (!ctx) throw new Error('usePeriod must be used within PeriodProvider')
  return ctx
}
