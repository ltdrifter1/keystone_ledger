import { useEngagement } from '../period/PeriodContext'

export function EngagementChip() {
  const { year, month, setYear, setMonth, label, entityId, setEntityId, entities } = useEngagement()

  return (
    <div className="engagement-chip" title="Sticky engagement context for the whole app">
      <div className="engagement-chip-row">
        <span className="period-chip-label">Entity</span>
        <select
          className="select engagement-chip-select"
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
          aria-label="Engagement entity"
        >
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.code}
            </option>
          ))}
        </select>
      </div>
      <div className="engagement-chip-row">
        <span className="period-chip-label">Period</span>
        <input
          className="input period-chip-input"
          type="number"
          value={year}
          onChange={(e) => setYear(Number(e.target.value) || year)}
          aria-label="Period year"
        />
        <input
          className="input period-chip-input"
          type="number"
          min={1}
          max={12}
          value={month}
          onChange={(e) => setMonth(Number(e.target.value) || month)}
          aria-label="Period month"
        />
        <span className="badge ok">{label}</span>
      </div>
    </div>
  )
}

/** @deprecated */
export function PeriodChip() {
  return <EngagementChip />
}
