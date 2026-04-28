type RuntimeCrashPanelProps = {
  onReload: () => void
}

export function RuntimeCrashPanel({ onReload }: RuntimeCrashPanelProps) {
  return (
    <main className="relative min-h-screen bg-ot-bg">
      <div className="absolute inset-y-0 left-0 w-1.5 bg-ot-red" aria-hidden="true" />
      <div className="grid min-h-screen content-start gap-5 px-6 pb-10 pl-[38px] pr-6 pt-14 max-[720px]:gap-4 max-[720px]:px-4 max-[720px]:pl-6 max-[720px]:pt-10">
        <div className="grid gap-3 border-y-2 border-ot-ink py-5 max-[720px]:py-4">
          <p className="eyebrow text-ot-red">Application halted</p>
          <h1 className="m-0 max-w-[10ch] font-display text-[clamp(3.3rem,8vw,6.4rem)] font-black uppercase leading-[0.86] tracking-[-0.04em] text-ot-ink">
            Oracle Tutor halted.
          </h1>
        </div>

        <div className="grid max-w-[44rem] gap-3">
          <p className="m-0 text-[0.8125rem] leading-[1.6] text-ot-ink">
            Oracle Tutor stopped before the interface could finish rendering.
          </p>
        </div>

        <div className="grid max-w-[44rem] gap-3 border-t-2 border-ot-ink pt-4">
          <p className="m-0 text-[0.6875rem] uppercase leading-[1.55] tracking-[0.14em] text-ot-muted">
            Recovery action
          </p>
          <p className="m-0 text-[0.75rem] uppercase leading-[1.6] tracking-[0.12em] text-ot-muted">
            Reload Oracle Tutor.
          </p>
          <button
            type="button"
            onClick={onReload}
            className="min-h-11 justify-self-start border-2 border-ot-ink bg-transparent px-4 font-display text-[0.75rem] font-black uppercase tracking-[0.12em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none"
          >
            Reload Oracle Tutor
          </button>
        </div>
      </div>
    </main>
  )
}
