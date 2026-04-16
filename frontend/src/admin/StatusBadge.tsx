type Props = { status: string }

function statusTone(status: string) {
  if (status === 'active' || status === 'succeeded' || status === 'ready') return 'bg-ot-ink text-ot-bg'
  if (status === 'running' || status === 'embedding') return 'bg-ot-yellow text-ot-ink'
  if (status === 'pending' || status === 'uploaded') return 'bg-ot-surface text-ot-ink'
  if (status === 'failed') return 'bg-ot-red text-ot-bg'
  return 'bg-ot-line text-ot-ink'
}

export function StatusBadge({ status }: Props) {
  return (
    <span className={`inline-block border-2 border-ot-ink px-2 py-1 text-[0.72rem] uppercase tracking-[0.08em] ${statusTone(status)}`}>
      {status}
    </span>
  )
}
