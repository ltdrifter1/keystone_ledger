export function money(value: string | number | null | undefined, currency?: string): string {
  const n = typeof value === 'string' ? Number(value) : value ?? 0
  const formatted = new Intl.NumberFormat('en-CA', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
  return currency ? `${currency} ${formatted}` : formatted
}

export function compactMoney(value: string | number, currency?: string): string {
  const n = typeof value === 'string' ? Number(value) : value
  const abs = Math.abs(n)
  let text: string
  if (abs >= 1_000_000) text = `${(n / 1_000_000).toFixed(2)}M`
  else if (abs >= 1_000) text = `${(n / 1_000).toFixed(1)}K`
  else text = n.toFixed(2)
  return currency ? `${currency} ${text}` : text
}
