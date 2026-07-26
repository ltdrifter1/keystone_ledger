import { usePeriod } from '../period/PeriodContext'

export function PeriodChip() {
  const { year, month, setYear, setMonth, label } = usePeriod()

  return (
    <div className="period-chip" title="Engagement period — shared across Close, Reports, and Working Papers">
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
  )
}
