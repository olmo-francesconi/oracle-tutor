type SearchErrorPanelProps = {
  message: string
}

export function SearchErrorPanel({ message }: SearchErrorPanelProps) {
  return (
    <div className="grid gap-3 border-y-2 border-ot-ink py-4">
      <div className="flex items-center gap-3">
        <span className="h-0.5 w-12 bg-ot-red" aria-hidden="true" />
        <p className="eyebrow text-ot-red">Search failed</p>
      </div>
      <p className="m-0 max-w-[15ch] font-display text-[clamp(1.9rem,4vw,2.8rem)] font-black uppercase leading-[0.88] tracking-[-0.03em] text-ot-ink">
        Results unavailable.
      </p>
      <p className="m-0 max-w-[62ch] text-[0.75rem] uppercase leading-[1.6] tracking-[0.11em] text-ot-muted">
        {message}
      </p>
    </div>
  )
}
