export const BUSINESS_TZ = 'Asia/Shanghai'

const BUSINESS_LOCAL_DATETIME_RE =
  /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/

export function parseBusinessDate(value: string | Date): Date {
  if (value instanceof Date) return value
  const text = String(value || '').trim()
  const match = text.match(BUSINESS_LOCAL_DATETIME_RE)
  if (!match) return new Date(text)
  const [, year, month, day, hour = '00', minute = '00', second = '00'] = match
  const utcMillis = Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour) - 8,
    Number(minute),
    Number(second),
  )
  return new Date(utcMillis)
}

export function getBusinessDayKey(value: string | Date): string {
  const dt = parseBusinessDate(value)
  if (Number.isNaN(dt.getTime())) return ''
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: BUSINESS_TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(dt)
  const year = parts.find((p) => p.type === 'year')?.value || '1970'
  const month = parts.find((p) => p.type === 'month')?.value || '01'
  const day = parts.find((p) => p.type === 'day')?.value || '01'
  return `${year}-${month}-${day}`
}
