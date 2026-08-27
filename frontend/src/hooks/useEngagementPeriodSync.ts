import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useEngagement } from '../period/PeriodContext'

/**
 * Keep engagement period and URL ?year=&month= in sync.
 * URL wins on first hydrate when present; thereafter chip changes write back to URL.
 */
export function useEngagementPeriodSync(opts?: { preserveKeys?: string[] }) {
  const { year, month, setPeriod } = useEngagement()
  const [params, setParams] = useSearchParams()
  const hydrated = useRef(false)
  const preserveKeys = opts?.preserveKeys ?? []

  // URL → context (once on mount / when URL period changes while still hydrating)
  useEffect(() => {
    const y = params.get('year')
    const m = params.get('month')
    if (y && m) {
      const yi = Number(y)
      const mi = Number(m)
      if (yi && mi && (yi !== year || mi !== month)) {
        setPeriod(yi, mi)
      }
    }
    hydrated.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Context → URL after hydrate
  useEffect(() => {
    if (!hydrated.current) return
    const next = new URLSearchParams(params)
    let changed = false
    if (next.get('year') !== String(year)) {
      next.set('year', String(year))
      changed = true
    }
    if (next.get('month') !== String(month)) {
      next.set('month', String(month))
      changed = true
    }
    // Drop keys we don't care about? Keep preserveKeys + everything else.
    void preserveKeys
    if (changed) setParams(next, { replace: true })
  }, [year, month, params, setParams, preserveKeys])
}
