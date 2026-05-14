interface SearchBootingNoticeProps {
  id: string
  variant: 'home' | 'topbar'
}

export function SearchBootingNotice({ id, variant }: SearchBootingNoticeProps) {
  return (
    <div
      className={[
        'animate-ot-fade-slide-in origin-top border-2 border-t-0 border-ot-ink bg-ot-surface',
        variant === 'topbar'
          ? 'absolute inset-x-[-2px] top-full z-40 border-t-2'
          : 'absolute inset-x-0 top-full z-30',
      ].join(' ')}
      id={id}
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-col gap-1 px-[14px] py-4">
        <span className="eyebrow text-ot-muted">warming up</span>
        <span className="text-[0.95rem] leading-[1.4] text-ot-ink">
          the oracle was asleep. suggestions in a moment
          <span className="ot-booting-dots ml-[1px]" aria-hidden="true">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </span>
      </div>
    </div>
  )
}
