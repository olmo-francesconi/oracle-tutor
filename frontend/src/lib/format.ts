const TIMESTAMP_FORMAT = new Intl.DateTimeFormat('en', {
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

export function formatTimestamp(value?: string | null) {
  if (!value) return 'not yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return TIMESTAMP_FORMAT.format(date)
}

export function formatBytes(size: number) {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
