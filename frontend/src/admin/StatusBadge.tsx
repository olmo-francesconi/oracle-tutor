type Props = { status: string }

function statusTone(status: string) {
  switch (status) {
    case 'active':
    case 'ready':
      return 'bg-ot-ink text-ot-bg'
    case 'embedding':
      return 'bg-ot-yellow text-ot-ink'
    case 'uploaded':
      return 'bg-ot-surface text-ot-ink'
    case 'archived':
      return 'bg-ot-line text-ot-ink'
    case 'failed':
      return 'bg-ot-red text-ot-bg'
    default:
      return 'bg-ot-line text-ot-ink'
  }
}

export function StatusBadge({ status }: Props) {
  return (
    <span className={`inline-block border-2 border-ot-ink px-2 py-1 text-[0.72rem] uppercase tracking-[0.08em] ${statusTone(status)}`}>
      {status}
    </span>
  )
}
