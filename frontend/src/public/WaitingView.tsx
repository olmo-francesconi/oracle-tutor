import { useEffect, useState } from 'react'

const STATUS_MESSAGES = [
  'Untapping the permanents.',
  'Shuffling the library.',
  'Consulting the spread.',
  'Drawing seven cards.',
  'Casting divination.',
  'Resolving the stack.',
] as const

const MESSAGE_INTERVAL_MS = 2500
const SLOW_THRESHOLD_ATTEMPTS = 12

type Props = {
  attempts: number
  error: Error | null
}

export function WaitingView({ attempts, error }: Props) {
  const [msgIndex, setMsgIndex] = useState(0)

  useEffect(() => {
    if (error) return
    const id = window.setInterval(
      () => setMsgIndex((i) => (i + 1) % STATUS_MESSAGES.length),
      MESSAGE_INTERVAL_MS
    )
    return () => window.clearInterval(id)
  }, [error])

  const isSlow = !error && attempts >= SLOW_THRESHOLD_ATTEMPTS
  const eyebrow = error ? 'Oracle Tutor · Elsewhere' : 'Oracle Tutor · Waking'
  const heading = error ? 'No answer from the stack.' : STATUS_MESSAGES[msgIndex]
  const subtext = error
    ? 'the semantic service is unreachable. try again in a minute.'
    : isSlow
      ? 'first wake of the day takes a moment. your search will land here when the stack resolves.'
      : 'your search will land here when the stack resolves.'

  return (
    <>
      <div className="fixed inset-y-0 left-0 z-20 w-1.5 bg-ot-red" aria-hidden="true" />

      <section
        className="relative z-20 grid w-full max-w-[560px] gap-7 animate-ot-fade-in motion-reduce:animate-none"
        aria-label="Loading"
        role="status"
        aria-live="polite"
      >
        <div className="grid gap-3 px-[18px] text-left max-[720px]:px-[14px]">
          <p className="eyebrow">{eyebrow}</p>
          <div className="h-0.5 w-full max-w-[18.5rem] bg-ot-ink" />
          <h1
            key={heading}
            className="m-0 font-display text-[clamp(2.4rem,5.5vw,3.5rem)] font-black uppercase leading-[0.9] tracking-[-0.02em] text-ot-ink animate-ot-fade-slide-in motion-reduce:animate-none"
          >
            {heading}
          </h1>
        </div>

        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 px-[18px] max-[720px]:px-[14px]">
          <span
            aria-hidden="true"
            className={[
              'mt-[6px] block h-2 w-2',
              error
                ? 'bg-ot-muted'
                : 'bg-ot-red animate-[ot-pulse-square_1600ms_ease-in-out_infinite] motion-reduce:animate-none',
            ].join(' ')}
          />
          <p className="m-0 max-w-[40ch] text-[0.85rem] lowercase leading-[1.55] tracking-[0.04em] text-ot-muted">
            {subtext}
          </p>
        </div>
      </section>
    </>
  )
}
