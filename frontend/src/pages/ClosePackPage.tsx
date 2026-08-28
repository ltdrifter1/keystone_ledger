import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  CheckCircle2,
  Upload,
  RefreshCw,
  Lock,
  AlertTriangle,
  ListChecks,
  Rows3,
  ArrowRight,
  Radio,
  BookPlus,
} from 'lucide-react'
import {
  api,
  type Account,
  type BankAccount,
  type BankFeed,
  type CloseException,
  type CloseNextAction,
  type ClosePackStatus,
  type MonthCloseOverview,
  type ReconWorkspace,
} from '../api'
import { AccountPicker } from '../components/AccountPicker'
import { BankInboxPanel } from '../components/BankInboxPanel'
import { JournalVoucherModal } from '../components/JournalVoucherModal'
import { useToast } from '../hooks/useToast'
import { money } from '../lib/format'
import { useEngagement } from '../period/PeriodContext'

type Mode = 'exceptions' | 'items'

export function ClosePackPage() {
  const {
    year: periodYear,
    month: periodMonth,
    setPeriod,
    entityId,
    entityCode,
  } = useEngagement()
  const [searchParams, setSearchParams] = useSearchParams()
  const year = String(periodYear)
  const month = String(periodMonth)
  const [banks, setBanks] = useState<BankAccount[]>([])
  const [feeds, setFeeds] = useState<BankFeed[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [overview, setOverview] = useState<MonthCloseOverview | null>(null)
  const [active, setActive] = useState<ClosePackStatus | null>(null)
  const [workspace, setWorkspace] = useState<ReconWorkspace | null>(null)
  const [bankId, setBankId] = useState(searchParams.get('bank') || '')
  const [ending, setEnding] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rememberRule, setRememberRule] = useState(true)
  const [mode, setMode] = useState<Mode>((searchParams.get('mode') as Mode) || 'exceptions')
  const [kindFilter, setKindFilter] = useState(searchParams.get('filter') || '')
  const [showUnclearedOnly, setShowUnclearedOnly] = useState(searchParams.get('filter') === 'uncleared')
  const [journalOpen, setJournalOpen] = useState(false)
  const [journalLed, setJournalLed] = useState(false)
  const [monthLocked, setMonthLocked] = useState(false)
  const { toast, show } = useToast()

  useEffect(() => {
    const y = searchParams.get('year')
    const m = searchParams.get('month')
    if (y && m) {
      const yi = Number(y)
      const mi = Number(m)
      if (yi && mi && (yi !== periodYear || mi !== periodMonth)) {
        setPeriod(yi, mi)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const syncUrl = useCallback(
    (next: { year?: string; month?: string; bank?: string; mode?: Mode; filter?: string }) => {
      const params = new URLSearchParams()
      params.set('year', next.year ?? year)
      params.set('month', next.month ?? month)
      const bank = next.bank ?? bankId
      if (bank) params.set('bank', bank)
      params.set('mode', next.mode ?? mode)
      const filter = next.filter !== undefined ? next.filter : kindFilter
      if (filter) params.set('filter', filter)
      setSearchParams(params, { replace: true })
    },
    [year, month, bankId, mode, kindFilter, setSearchParams],
  )

  // Keep URL year/month aligned with sticky engagement chip
  useEffect(() => {
    const currentY = searchParams.get('year')
    const currentM = searchParams.get('month')
    if (currentY === year && currentM === String(Number(month))) return
    syncUrl({})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, month])

  const loadOverview = useCallback(async () => {
    const data = await api.closeMonthOverview(Number(year), Number(month))
    setOverview(data)
    return data
  }, [year, month])

  useEffect(() => {
    Promise.all([api.bankAccounts(), api.accounts(), api.bankFeeds()])
      .then(([b, a, f]) => {
        setBanks(b)
        setAccounts(a)
        setFeeds(f)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!entityId) return
    api
      .entityPeriodLock(Number(entityId), Number(year), Number(month))
      .then((lock) => {
        setJournalLed(Boolean(lock.journal_led))
        setMonthLocked(Boolean(lock.is_locked))
      })
      .catch(() => undefined)
  }, [entityId, year, month])

  // Keep selected bank inside the sticky engagement entity
  useEffect(() => {
    if (!entityId || !banks.length) return
    const scoped = banks.filter((b) => String(b.entity_id) === entityId)
    if (!scoped.length) return
    const stillValid = scoped.some((b) => String(b.id) === bankId)
    if (!stillValid) {
      setBankId(String(scoped[0].id))
      setActive(null)
      setWorkspace(null)
    }
  }, [entityId, banks, bankId])

  useEffect(() => {
    loadOverview()
      .then((data) => {
        const scoped = entityId
          ? data.packs.filter((p) => String(p.entity_id ?? '') === entityId || p.entity_code === entityCode)
          : data.packs
        const fromUrl = searchParams.get('bank')
        const targetId = fromUrl || bankId
        const urlMode = (searchParams.get('mode') as Mode) || mode
        const urlFilter = searchParams.get('filter')
        const inScope = (id: string) => scoped.some((p) => String(p.bank_account_id) === String(id))
        if (targetId && inScope(targetId)) {
          const pack = scoped.find((p) => String(p.bank_account_id) === String(targetId))
          if (urlFilter != null) {
            setKindFilter(urlFilter)
            setShowUnclearedOnly(urlFilter === 'uncleared')
          }
          if (pack) void openPack(pack, { skipUrl: true, mode: urlMode })
        } else if (urlFilter) {
          setKindFilter(urlFilter)
          setShowUnclearedOnly(urlFilter === 'uncleared')
          const pack = scoped[0]
          if (pack) void openPack(pack, { skipUrl: true, mode: urlMode })
        } else if (data.next_actions[0]) {
          const action = data.next_actions.find((a) =>
            scoped.some((p) => p.bank_account_id === a.bank_account_id),
          )
          if (action) {
            const pack = scoped.find((p) => p.bank_account_id === action.bank_account_id)
            if (pack) {
              const nextMode = (action.mode as Mode) || 'exceptions'
              setMode(nextMode)
              setKindFilter(action.filter || '')
              setShowUnclearedOnly(action.filter === 'uncleared')
              void openPack(pack, { skipUrl: true, mode: nextMode })
            }
          } else if (scoped[0]) {
            void openPack(scoped[0], { skipUrl: true, mode: urlMode })
          }
        } else if (scoped[0]) {
          void openPack(scoped[0], { skipUrl: true, mode: urlMode })
        }
      })
      .catch((e: Error) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadOverview, entityId])

  const loadWorkspace = async (reconId: number) => {
    const ws = await api.reconWorkspace(reconId)
    setWorkspace(ws)
    return ws
  }

  const openPack = async (
    pack: ClosePackStatus,
    opts?: { skipUrl?: boolean; mode?: Mode },
  ) => {
    setBankId(String(pack.bank_account_id))
    if (pack.statement_ending_balance != null) {
      setEnding(String(pack.statement_ending_balance))
    } else {
      setEnding('')
    }
    if (!opts?.skipUrl) {
      syncUrl({ bank: String(pack.bank_account_id) })
    }
    if (!pack.reconciliation_id) {
      setActive(pack)
      setWorkspace(null)
      return
    }
    try {
      const fresh = await api.getClosePack(pack.reconciliation_id)
      setActive(fresh)
      const effectiveMode = opts?.mode ?? mode
      if (effectiveMode === 'items') {
        await loadWorkspace(pack.reconciliation_id)
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    if (mode === 'items' && active?.reconciliation_id) {
      loadWorkspace(active.reconciliation_id).catch((e: Error) => setError(e.message))
    }
  }, [mode, active?.reconciliation_id])

  const runPack = async () => {
    if (!bankId || ending === '') {
      show('Choose a bank and statement ending balance')
      return
    }
    setRunning(true)
    setError(null)
    try {
      const result = await api.runClosePack({
        bankAccountId: Number(bankId),
        periodYear: Number(year),
        periodMonth: Number(month),
        statementEndingBalance: Number(ending),
        file,
      })
      setActive(result)
      setFile(null)
      await loadOverview()
      api.bankFeeds().then(setFeeds).catch(() => undefined)
      if (result.can_lock) {
        show(`Ready to lock — ${result.auto_cleared ?? 0} auto-cleared`)
      } else {
        show(
          `Pack ran — ${result.blocking_count} blocking exception${result.blocking_count === 1 ? '' : 's'}`,
        )
      }
      syncUrl({ bank: String(result.bank_account_id), mode: 'exceptions' })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const runFromFeed = async () => {
    if (!bankId) {
      show('Choose a bank')
      return
    }
    setRunning(true)
    setError(null)
    try {
      const result = await api.runCloseFromFeed({
        bankAccountId: Number(bankId),
        periodYear: Number(year),
        periodMonth: Number(month),
      })
      setActive(result)
      setEnding(result.statement_ending_balance != null ? String(result.statement_ending_balance) : '')
      await loadOverview()
      api.bankFeeds().then(setFeeds).catch(() => undefined)
      const pulled = result.feed_imported ?? 0
      if (result.can_lock) {
        show(`Closed from feed — ${pulled} new item(s), ready to lock`)
      } else {
        show(`Feed synced — ${pulled} new · ${result.blocking_count} blocking`)
      }
      syncUrl({ bank: String(result.bank_account_id), mode: 'exceptions' })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const refreshActive = async () => {
    if (!active?.reconciliation_id) return
    const fresh = await api.refreshClosePack(active.reconciliation_id)
    setActive(fresh)
    if (mode === 'items') await loadWorkspace(active.reconciliation_id)
    await loadOverview()
    show('Rules re-applied · auto-clear refreshed')
  }

  const categorize = async (ex: CloseException, accountId: number) => {
    if (!active?.reconciliation_id) return
    try {
      const fresh = await api.closeCategorizeException(active.reconciliation_id, ex.transaction_id, {
        account_id: accountId,
        create_rule: rememberRule,
        clear_after: true,
      })
      setActive(fresh)
      if (mode === 'items') await loadWorkspace(active.reconciliation_id)
      await loadOverview()
      show(rememberRule ? 'Categorized + cleared · rule remembered' : 'Categorized + cleared')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const clearItem = async (transactionId: number, isCleared = true) => {
    if (!active?.reconciliation_id) return
    const fresh = await api.closeClearException(active.reconciliation_id, transactionId, isCleared)
    setActive(fresh)
    if (mode === 'items') await loadWorkspace(active.reconciliation_id)
    await loadOverview()
  }

  const voidDup = async (ex: CloseException) => {
    if (!active?.reconciliation_id) return
    const fresh = await api.closeVoidDuplicate(active.reconciliation_id, ex.transaction_id)
    setActive(fresh)
    await loadOverview()
    show('Duplicate voided')
  }

  const clearAllCategorized = async () => {
    if (!active?.reconciliation_id) return
    try {
      const ws = await api.clearAllRecon(active.reconciliation_id, true)
      setWorkspace(ws)
      const fresh = await api.getClosePack(active.reconciliation_id)
      setActive(fresh)
      await loadOverview()
      show('Cleared all categorized items')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const syncItems = async () => {
    if (!active?.reconciliation_id) return
    const ws = await api.syncRecon(active.reconciliation_id)
    setWorkspace(ws)
    const fresh = await api.getClosePack(active.reconciliation_id)
    setActive(fresh)
    show(`Synced${ws.added ? ` · +${ws.added} items` : ''}`)
  }

  const lockActive = async () => {
    if (!active?.reconciliation_id) return
    try {
      const fresh = await api.lockClosePack(active.reconciliation_id)
      setActive(fresh)
      setWorkspace(null)
      await loadOverview()
      show('Period locked')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const entityPacks = useMemo(() => {
    if (!overview) return []
    if (!entityId) return overview.packs
    return overview.packs.filter((p) => String(p.entity_id ?? '') === entityId || p.entity_code === entityCode)
  }, [overview, entityId, entityCode])

  const entityActions = useMemo(() => {
    if (!overview) return []
    const ids = new Set(entityPacks.map((p) => p.bank_account_id))
    return overview.next_actions.filter((a) => ids.has(a.bank_account_id))
  }, [overview, entityPacks])

  const entityBanks = useMemo(() => {
    if (!entityId) return banks
    return banks.filter((b) => String(b.entity_id) === entityId)
  }, [banks, entityId])

  const entityStats = useMemo(() => {
    const locked = entityPacks.filter((p) => p.is_locked).length
    const ready = entityPacks.filter((p) => p.can_lock).length
    const inProgress = entityPacks.filter(
      (p) => p.status !== 'not_started' && p.status !== 'locked' && !p.can_lock,
    ).length
    const canLockEntity =
      entityPacks.length > 0 && entityPacks.every((p) => p.is_locked || p.can_lock) && ready > 0
    return { locked, ready, inProgress, canLockEntity, total: entityPacks.length }
  }, [entityPacks])

  const lockMonthAll = async () => {
    try {
      const ready = entityPacks.filter((p) => p.can_lock && p.reconciliation_id && !p.is_locked)
      let locked = 0
      const errors: string[] = []
      for (const pack of ready) {
        try {
          await api.lockClosePack(pack.reconciliation_id!)
          locked += 1
        } catch (e) {
          errors.push(`${pack.bank_account_name}: ${(e as Error).message}`)
        }
      }
      const data = await loadOverview()
      if (active?.reconciliation_id) {
        const match = data.packs.find((p) => p.reconciliation_id === active.reconciliation_id)
        if (match) setActive(match)
      }
      if (errors.length) {
        show(`Locked ${locked} · ${errors.length} bank(s) not ready`)
      } else {
        show(`Locked ${locked} bank(s) for ${entityCode ?? 'entity'}`)
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const applyNextAction = (action: CloseNextAction) => {
    const pack = overview?.packs.find((p) => p.bank_account_id === action.bank_account_id)
    const nextMode = (action.mode as Mode) || 'exceptions'
    setMode(nextMode)
    setKindFilter(action.filter || '')
    setShowUnclearedOnly(action.filter === 'uncleared')
    syncUrl({
      bank: String(action.bank_account_id),
      mode: nextMode,
      filter: action.filter || '',
    })
    if (pack) void openPack(pack, { skipUrl: true, mode: nextMode })
    if (action.kind === 'feed_sync') {
      setBankId(String(action.bank_account_id))
      void (async () => {
        setBankId(String(action.bank_account_id))
        // run after bankId state — pass id directly
        setRunning(true)
        setError(null)
        try {
          const result = await api.runCloseFromFeed({
            bankAccountId: action.bank_account_id,
            periodYear: Number(year),
            periodMonth: Number(month),
          })
          setActive(result)
          setEnding(
            result.statement_ending_balance != null ? String(result.statement_ending_balance) : '',
          )
          await loadOverview()
          api.bankFeeds().then(setFeeds).catch(() => undefined)
          show(`Closed from feed — ${result.feed_imported ?? 0} new item(s)`)
        } catch (e) {
          setError((e as Error).message)
        } finally {
          setRunning(false)
        }
      })()
    }
  }

  const exceptionsByKind = useMemo(() => {
    const map = new Map<string, CloseException[]>()
    for (const ex of active?.exceptions ?? []) {
      if (kindFilter && ex.kind !== kindFilter) continue
      const list = map.get(ex.kind) ?? []
      list.push(ex)
      map.set(ex.kind, list)
    }
    return map
  }, [active, kindFilter])

  const visibleItems = useMemo(() => {
    if (!workspace) return []
    return workspace.items.filter((it) => {
      if (showUnclearedOnly && it.is_cleared) return false
      if (kindFilter === 'uncategorized' && !(it.status === 'uncategorized' && !it.is_split)) return false
      return true
    })
  }, [workspace, showUnclearedOnly, kindFilter])

  const kindLabel: Record<string, string> = {
    uncategorized: 'Uncategorized',
    duplicate: 'Duplicates',
    difference: 'Difference drivers',
    intercompany: 'Intercompany',
    uncleared: 'Uncleared',
  }

  const diffZero = active?.difference != null ? Math.abs(active.difference) < 0.0001 : false
  const clearedTotal =
    active?.cleared_total ??
    (active?.beginning_balance != null && active?.calculated_balance != null
      ? active.calculated_balance - active.beginning_balance
      : null)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Books</h1>
          <p>
            Bank inbox for {entityCode ?? 'entity'} · {year}-{String(month).padStart(2, '0')}. Mark
            Transfer or Intercompany, or pick a GL. Rules and FX live in Settings.
          </p>
        </div>
        <div className="toolbar">
          <button
            className="btn primary"
            disabled={!entityStats.canLockEntity}
            onClick={() => void lockMonthAll()}
          >
            <Lock size={14} /> Lock entity banks
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {entityId && (
        <BankInboxPanel
          year={Number(year)}
          month={Number(month)}
          entityId={entityId}
          entityCode={entityCode}
          onChanged={() => {
            void loadOverview()
            api.bankFeeds().then(setFeeds).catch(() => undefined)
          }}
          onMessage={show}
        />
      )}

      {journalLed && (
        <section className="panel">
          <div className="panel-header">
            <h2>Journals</h2>
            <span className={`badge ${monthLocked ? 'ok' : ''}`}>{monthLocked ? 'month locked' : 'month open'}</span>
          </div>
          <p className="hint">
            Cash recon is N/A while cash is nil. Post or review journals here. Late items after lock go
            through post-close adj (PCA).
          </p>
        </section>
      )}

      <div className="filters close-period-bar">
        <span className="hint">
          Engagement {entityCode ?? '—'} · {year}-{String(month).padStart(2, '0')}
        </span>
        {overview && (
          <span className="badge ok">
            {entityStats.locked}/{entityStats.total} locked · {entityStats.ready} ready
            {entityStats.inProgress ? ` · ${entityStats.inProgress} in progress` : ''}
          </span>
        )}
        {entityStats.total > 0 && entityStats.locked === entityStats.total && (
          <span className="badge ok">
            <CheckCircle2 size={12} /> Entity banks locked
          </span>
        )}
        <button className="btn" type="button" onClick={() => setJournalOpen(true)}>
          <BookPlus size={14} /> Journal
        </button>
      </div>

      {entityActions.length > 0 && (
        <section className="panel close-next-panel">
          <div className="panel-header">
            <h2>Next actions</h2>
            <span className="hint">{entityActions.length} ranked</span>
          </div>
          <div className="close-next-list">
            {entityActions.slice(0, 6).map((action) => (
              <button
                key={action.key}
                type="button"
                className={`close-next-card ${action.kind === 'ready_to_lock' ? 'ok' : 'warn'}`}
                onClick={() => applyNextAction(action)}
              >
                <div>
                  <strong>{action.title}</strong>
                  <span className="hint">{action.detail}</span>
                </div>
                <ArrowRight size={16} />
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="close-bank-strip">
        {entityPacks.length === 0 && (
          <p className="hint">No bank accounts for {entityCode ?? 'this entity'}.</p>
        )}
        {entityPacks.map((p) => (
          <button
            key={p.bank_account_id}
            type="button"
            className={`close-bank-chip ${active?.bank_account_id === p.bank_account_id ? 'active' : ''} ${p.is_locked ? 'locked' : p.can_lock ? 'ready' : p.blocking_count ? 'blocked' : ''}`}
            onClick={() => void openPack(p)}
          >
            <span className="close-bank-name">{p.bank_account_name}</span>
            <span className="badge">{p.entity_code}</span>
            <span className="hint">
              {p.is_locked
                ? 'locked'
                : p.can_lock
                  ? 'ready'
                  : p.status === 'not_started'
                    ? (p.feed_status === 'connected'
                      ? p.feed_pending
                        ? `feed · ${p.feed_pending} new`
                        : 'feed live'
                      : 'not started')
                    : `${p.blocking_count} block`}
            </span>
            <span className="close-bank-diff">
              {p.difference == null ? '—' : money(p.difference)}
            </span>
          </button>
        ))}
      </div>

      <div className="close-pack-layout">
        <section className="panel">
          <div className="panel-header">
            <h2>Run / update</h2>
          </div>
          <div className="close-run-form">
            <select
              className="select"
              value={bankId}
              onChange={(e) => {
                setBankId(e.target.value)
                const pack = overview?.packs.find((p) => String(p.bank_account_id) === e.target.value)
                if (pack) void openPack(pack)
              }}
            >
              {entityBanks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.currency})
                </option>
              ))}
            </select>
            {(() => {
              const feed = feeds.find((f) => String(f.bank_account_id) === bankId)
              const connected = feed?.status === 'connected'
              return (
                <>
                  {connected && (
                    <div className="feed-run-banner">
                      <Radio size={16} />
                      <div>
                        <strong>Live feed connected</strong>
                        <div className="hint">
                          {feed.pending_count
                            ? `${feed.pending_count} new item(s) waiting`
                            : 'Caught up'}
                          {feed.last_balance != null
                            ? ` · balance ${money(feed.last_balance, feed.currency)}`
                            : ''}
                          . Ending balance is taken from the bank at period end.
                        </div>
                      </div>
                    </div>
                  )}
                  <button
                    className="btn primary"
                    disabled={running || active?.is_locked || !connected}
                    onClick={() => void runFromFeed()}
                  >
                    {running
                      ? 'Syncing…'
                      : connected
                        ? 'Sync & close from feed'
                        : 'Connect a feed on Banks'}
                  </button>
                  <details className="manual-close">
                    <summary>Manual statement (CSV / typed balance)</summary>
                    <input
                      className="input"
                      type="number"
                      step="0.01"
                      placeholder="Statement ending balance"
                      value={ending}
                      onChange={(e) => setEnding(e.target.value)}
                      disabled={active?.is_locked}
                    />
                    <label className="btn">
                      <Upload size={14} />
                      {file ? file.name : 'Statement CSV/Excel (optional)'}
                      <input
                        type="file"
                        accept=".csv,.xlsx,.xls"
                        hidden
                        disabled={active?.is_locked}
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                      />
                    </label>
                    <button
                      className="btn"
                      disabled={running || active?.is_locked}
                      onClick={() => void runPack()}
                    >
                      {running ? 'Running…' : active?.reconciliation_id ? 'Update recon pack' : 'Run recon pack'}
                    </button>
                  </details>
                </>
              )
            })()}
            <p className="hint">
              Feed close: sync → apply rules → open recon with the bank’s period-end balance →
              auto-clear categorized items.
            </p>
          </div>
        </section>

        <section className="panel close-exceptions-panel">
          <div className="panel-header">
            <h2>
              {active
                ? `${active.bank_account_name ?? 'Bank'} · ${active.period_label}`
                : 'Workspace'}
            </h2>
            {active?.reconciliation_id && (
              <div className="toolbar">
                <div className="close-mode-toggle">
                  <button
                    type="button"
                    className={`btn ghost ${mode === 'exceptions' ? 'active-mode' : ''}`}
                    onClick={() => {
                      setMode('exceptions')
                      syncUrl({ mode: 'exceptions' })
                    }}
                  >
                    <ListChecks size={14} /> Exceptions
                  </button>
                  <button
                    type="button"
                    className={`btn ghost ${mode === 'items' ? 'active-mode' : ''}`}
                    onClick={() => {
                      setMode('items')
                      syncUrl({ mode: 'items' })
                    }}
                  >
                    <Rows3 size={14} /> All items
                  </button>
                </div>
                {active.status !== 'locked' && (
                  <>
                    <button className="btn" onClick={() => void refreshActive()}>
                      <RefreshCw size={14} /> Refresh
                    </button>
                    <button className="btn" onClick={() => setJournalOpen(true)}>
                      <BookPlus size={14} /> Journal
                    </button>
                    <button className="btn primary" disabled={!active.can_lock} onClick={() => void lockActive()}>
                      <Lock size={14} /> Complete & lock
                    </button>
                  </>
                )}
              </div>
            )}
          </div>

          {!active && (
            <p className="hint" style={{ padding: '1rem' }}>
              Select a bank from Next actions or the bank strip.
            </p>
          )}

          {active && (
            <>
              <div className="tie-strip close-tie-full">
                <div className="kpi">
                  <div className="kpi-label">Beginning</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {money(active.beginning_balance)}
                  </div>
                </div>
                <div className="tie-op">+</div>
                <div className="kpi">
                  <div className="kpi-label">Cleared</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {clearedTotal == null ? '—' : money(clearedTotal)}
                  </div>
                </div>
                <div className="tie-op">=</div>
                <div className="kpi">
                  <div className="kpi-label">Book</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {active.calculated_balance == null ? '—' : money(active.calculated_balance)}
                  </div>
                </div>
                <div className="tie-op">vs</div>
                <div className="kpi">
                  <div className="kpi-label">Statement</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {active.statement_ending_balance == null
                      ? '—'
                      : money(active.statement_ending_balance)}
                  </div>
                </div>
                <div className={`kpi ${diffZero ? 'ok' : 'warn'}`}>
                  <div className="kpi-label">Difference</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {active.difference == null ? '—' : money(active.difference)}
                  </div>
                </div>
                <div className={`kpi ${active.blocking_count === 0 ? 'ok' : 'warn'}`}>
                  <div className="kpi-label">Blocking</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {active.blocking_count}
                  </div>
                </div>
              </div>

              {active.is_locked && (
                <div className="close-locked-banner">
                  <CheckCircle2 size={16} /> Locked
                  {active.locked_at ? ` · ${new Date(active.locked_at).toLocaleString()}` : ''}
                </div>
              )}

              {active.can_lock && !active.is_locked && (
                <div className="close-ready-banner">
                  <CheckCircle2 size={16} /> Ready to lock — no blocking exceptions, difference is zero.
                </div>
              )}

              {!active.reconciliation_id && (
                <p className="hint" style={{ padding: '0 1rem 1rem' }}>
                  Not started. Sync the live feed (or enter a statement balance) and run the pack.
                </p>
              )}

              {mode === 'exceptions' && active.reconciliation_id && (
                <>
                  <div className="filters" style={{ padding: '0 1rem' }}>
                    <label className="btn ghost">
                      <input
                        type="checkbox"
                        checked={rememberRule}
                        onChange={(e) => setRememberRule(e.target.checked)}
                      />
                      Remember rules
                    </label>
                    <select
                      className="select"
                      value={kindFilter}
                      onChange={(e) => {
                        setKindFilter(e.target.value)
                        syncUrl({ filter: e.target.value })
                      }}
                    >
                      <option value="">All exception types</option>
                      {Object.keys(kindLabel).map((k) => (
                        <option key={k} value={k}>
                          {kindLabel[k]}
                        </option>
                      ))}
                    </select>
                    <Link
                      className="btn ghost"
                      to={`/transactions?bank_account_id=${active.bank_account_id}&uncategorized_only=true`}
                    >
                      Splits / bulk ledger
                    </Link>
                  </div>

                  {active.exception_count === 0 && !active.is_locked && (
                    <p className="hint" style={{ padding: '0 1rem 1rem' }}>
                      No exceptions. Cleared {active.cleared_count} · Uncleared {active.uncleared_count}{' '}
                      (timing). Switch to All items if you need the full register.
                    </p>
                  )}

                  {active.exception_count > 0 && (
                    <div className="exception-stack">
                      {[...exceptionsByKind.entries()].map(([kind, rows]) => (
                        <div key={kind} className="exception-group">
                          <div className="exception-group-head">
                            <AlertTriangle size={14} />
                            {kindLabel[kind] ?? kind}
                            <span className="badge">{rows.length}</span>
                          </div>
                          <div className="table-wrap">
                            <table className="data">
                              <thead>
                                <tr>
                                  <th>Date</th>
                                  <th>Description</th>
                                  <th className="num">Amount</th>
                                  <th>Action</th>
                                </tr>
                              </thead>
                              <tbody>
                                {rows.map((ex) => (
                                  <tr key={`${ex.kind}-${ex.transaction_id}`}>
                                    <td>
                                      {ex.txn_date}
                                      {!ex.in_period && <span className="badge">PRIOR</span>}
                                      {ex.blocking && <span className="badge open">BLOCK</span>}
                                    </td>
                                    <td className="desc-cell">
                                      <div>{ex.description}</div>
                                      <div className="hint">{ex.message}</div>
                                    </td>
                                    <td className="num">{money(ex.amount, ex.currency)}</td>
                                    <td onClick={(e) => e.stopPropagation()}>
                                      {kind === 'uncategorized' && !active.is_locked && (
                                        <AccountPicker
                                          accounts={accounts}
                                          placeholder="Categorize…"
                                          onSelect={(id) => void categorize(ex, id)}
                                        />
                                      )}
                                      {kind === 'duplicate' && !active.is_locked && (
                                        <div className="toolbar">
                                          <button className="btn ghost" onClick={() => void voidDup(ex)}>
                                            Void dup
                                          </button>
                                          <button
                                            className="btn ghost"
                                            onClick={() => void clearItem(ex.transaction_id, true)}
                                          >
                                            Keep & clear
                                          </button>
                                        </div>
                                      )}
                                      {(kind === 'difference' || kind === 'uncleared') &&
                                        !active.is_locked && (
                                          <div className="toolbar">
                                            <button
                                              className="btn ghost"
                                              onClick={() => void clearItem(ex.transaction_id, true)}
                                            >
                                              Clear
                                            </button>
                                            {ex.is_cleared && (
                                              <button
                                                className="btn ghost"
                                                onClick={() => void clearItem(ex.transaction_id, false)}
                                              >
                                                Unclear
                                              </button>
                                            )}
                                          </div>
                                        )}
                                      {kind === 'intercompany' && (
                                        <button
                                          className="btn ghost"
                                          onClick={() =>
                                            void api.autoMatchIc().then(async () => {
                                              await refreshActive()
                                              show('IC match attempted')
                                            })
                                          }
                                        >
                                          Match IC
                                        </button>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ))}
                      {exceptionsByKind.size === 0 && kindFilter && (
                        <p className="hint" style={{ padding: '1rem' }}>
                          No {kindLabel[kindFilter] ?? kindFilter} exceptions for this bank.
                        </p>
                      )}
                    </div>
                  )}
                </>
              )}

              {mode === 'items' && active.reconciliation_id && (
                <>
                  <div className="filters" style={{ padding: '0 0.85rem' }}>
                    <label className="btn ghost">
                      <input
                        type="checkbox"
                        checked={showUnclearedOnly}
                        onChange={(e) => setShowUnclearedOnly(e.target.checked)}
                      />
                      Uncleared only
                    </label>
                    <label className="btn ghost">
                      <input
                        type="checkbox"
                        checked={kindFilter === 'uncategorized'}
                        onChange={(e) => {
                          const next = e.target.checked ? 'uncategorized' : ''
                          setKindFilter(next)
                          syncUrl({ filter: next })
                        }}
                      />
                      Uncategorized
                    </label>
                    {active.status !== 'locked' && (
                      <>
                        <button className="btn" onClick={() => void syncItems()}>
                          Sync items
                        </button>
                        <button className="btn" onClick={() => void clearAllCategorized()}>
                          Clear categorized
                        </button>
                      </>
                    )}
                    <Link
                      className="btn ghost"
                      to={`/transactions?bank_account_id=${active.bank_account_id}`}
                    >
                      Splits / bulk
                    </Link>
                  </div>

                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Clr</th>
                          <th>Date</th>
                          <th>Description</th>
                          <th>Account</th>
                          <th className="num">Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {!workspace && (
                          <tr>
                            <td colSpan={5} className="hint">
                              Loading register…
                            </td>
                          </tr>
                        )}
                        {workspace &&
                          visibleItems.map((it) => (
                            <tr key={it.id} className={!it.in_period ? 'prior-item' : ''}>
                              <td>
                                <input
                                  type="checkbox"
                                  checked={it.is_cleared}
                                  disabled={active.is_locked}
                                  onChange={() => void clearItem(it.transaction_id, !it.is_cleared)}
                                />
                              </td>
                              <td>
                                {it.txn_date}
                                {!it.in_period && <span className="badge">PRIOR</span>}
                              </td>
                              <td>{it.description}</td>
                              <td onClick={(e) => e.stopPropagation()}>
                                {it.is_split ? (
                                  'Split'
                                ) : it.account_code ? (
                                  `${it.account_code} ${it.account_name}`
                                ) : active.is_locked ? (
                                  <span className="badge open">uncategorized</span>
                                ) : (
                                  <AccountPicker
                                    accounts={accounts}
                                    placeholder="Categorize…"
                                    onSelect={(id) =>
                                      void categorize(
                                        {
                                          kind: 'uncategorized',
                                          message: 'Uncategorized',
                                          transaction_id: it.transaction_id,
                                          txn_date: it.txn_date,
                                          description: it.description,
                                          amount: it.amount,
                                          currency: it.currency,
                                          status: it.status,
                                          is_split: it.is_split,
                                          is_duplicate: false,
                                          is_cleared: it.is_cleared,
                                          in_period: it.in_period,
                                          blocking: true,
                                        },
                                        id,
                                      )
                                    }
                                  />
                                )}
                              </td>
                              <td className="num">{money(it.amount, it.currency)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  {workspace && (
                    <p className="hint" style={{ padding: '0.75rem 1rem' }}>
                      Uncleared {workspace.uncleared_count} ({money(workspace.uncleared_total)}) carry
                      forward. Difference must be zero and cleared items categorized before lock.
                    </p>
                  )}
                </>
              )}
            </>
          )}
        </section>
      </div>
      <JournalVoucherModal
        open={journalOpen}
        accounts={accounts}
        sourceTransactionId={undefined}
        defaultDescription={
          active ? `Close adjustment · ${active.bank_account_name} ${active.period_label}` : undefined
        }
        onClose={() => setJournalOpen(false)}
        onPosted={() => {
          void refreshActive()
          void loadOverview()
        }}
      />
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
