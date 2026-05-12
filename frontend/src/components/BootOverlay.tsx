import { useEffect, useState } from 'react'
import { useApiReadyState } from '../lib/apiReadyContext'

const STATUS_MESSAGES = [
  'The Oracle untaps her permanents…',
  'Shuffling the omniscient library…',
  'Consulting the spread for guidance…',
  'Drawing seven cards from the multiverse…',
  'Casting Divination on the deck…',
  'Resolving the stack…',
]

const MANA_SYMBOLS = ['w', 'u', 'b', 'r', 'g'] as const
const MESSAGE_INTERVAL_MS = 2500
const SLOW_THRESHOLD_ATTEMPTS = 10

export function BootOverlay() {
  const { ready, attempts, error } = useApiReadyState()
  const [msgIndex, setMsgIndex] = useState(0)

  useEffect(() => {
    if (ready || error) return
    const id = setInterval(
      () => setMsgIndex((i) => (i + 1) % STATUS_MESSAGES.length),
      MESSAGE_INTERVAL_MS
    )
    return () => clearInterval(id)
  }, [ready, error])

  if (ready) return null

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Application loading"
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ animation: 'ot-boot-fade-in 300ms ease-out both' }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-[var(--color-ot-bg)] opacity-95" />

      {/* Panel */}
      <div
        className="relative flex flex-col items-center gap-6 border border-[var(--color-ot-line)] bg-[var(--color-ot-surface)] px-10 py-10 max-w-sm w-full mx-4"
        style={{ boxShadow: '4px 4px 0 var(--color-ot-line)' }}
      >
        {/* Mana symbols cycling */}
        <div className="relative h-10 w-10" aria-hidden="true">
          {MANA_SYMBOLS.map((color, i) => (
            <span
              key={color}
              className={`ms ms-${color} ms-cost ms-3x absolute inset-0 flex items-center justify-center`}
              style={{
                animation: `ot-mana-cycle ${MANA_SYMBOLS.length * MESSAGE_INTERVAL_MS}ms ${i * MESSAGE_INTERVAL_MS}ms ease-in-out infinite`,
                opacity: 0,
              }}
            />
          ))}
        </div>

        {/* Title */}
        <div className="text-center">
          <p className="eyebrow mb-2">Oracle Tutor</p>
          <p
            className="text-xl uppercase tracking-wide text-[var(--color-ot-ink)]"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            {error ? 'The Oracle is elsewhere' : STATUS_MESSAGES[msgIndex]}
          </p>
        </div>

        {/* Slow start notice */}
        {!error && attempts >= SLOW_THRESHOLD_ATTEMPTS && (
          <p className="text-center text-xs text-[var(--color-ot-muted)]">
            First visit in a while — this can take a moment.
          </p>
        )}

        {/* Error state */}
        {error && (
          <div className="flex flex-col items-center gap-3 text-center">
            <p className="text-xs text-[var(--color-ot-muted)]">
              Try refreshing in a minute.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="border border-[var(--color-ot-ink)] px-4 py-2 text-sm font-medium uppercase tracking-widest transition-colors hover:bg-[var(--color-ot-ink)] hover:text-[var(--color-ot-surface)] focus-visible:outline-[var(--color-ot-red)]"
            >
              Try again
            </button>
          </div>
        )}

        {/* Loading bar */}
        {!error && (
          <div className="h-0.5 w-full bg-[var(--color-ot-line)]" aria-hidden="true">
            <div
              className="h-full bg-[var(--color-ot-red)]"
              style={{ animation: 'ot-loading-pulse 900ms ease-in-out infinite alternate' }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
