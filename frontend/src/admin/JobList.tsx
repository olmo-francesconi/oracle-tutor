import type { SemanticJobSummary } from '../types/api'
import { StatusBadge } from './StatusBadge'

function formatTimestamp(value?: string | null) {
  if (!value) return 'not yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

type Props = {
  jobs: SemanticJobSummary[]
  loading: boolean
}

export function JobList({ jobs, loading }: Props) {
  return (
    <section className="grid gap-0 border-2 border-ot-ink bg-ot-surface">
      <div className="border-b-2 border-ot-ink px-5 py-4">
        <p className="eyebrow">Jobs</p>
        <h2 className="m-0 pt-2 font-display text-[2.1rem] font-black uppercase leading-[0.9] tracking-[-0.03em]">
          Queue and worker pulse
        </h2>
      </div>

      <div className="grid">
        {loading ? (
          <div className="animate-ot-loading-pulse px-5 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">Loading…</div>
        ) : jobs.length === 0 ? (
          <div className="px-5 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">
            No jobs queued yet.
          </div>
        ) : (
          jobs.map((job) => (
            <article
              key={job.id}
              className="grid gap-3 border-b-2 border-ot-line px-5 py-4 last:border-b-0"
            >
              <div className="flex items-start justify-between gap-4 max-[720px]:flex-col">
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-display text-[1.3rem] font-black uppercase leading-none tracking-[-0.02em]">
                      #{job.id} {job.job_type}
                    </span>
                    <StatusBadge status={job.status} />
                  </div>
                  <p className="m-0 break-words text-[0.75rem] uppercase tracking-[0.08em] text-ot-muted">
                    Requested by {job.requested_by}
                    {job.model_id ? ` / model ${job.model_id}` : ''}
                    {job.dataset_id ? ` / dataset ${job.dataset_id.slice(0, 8)}` : ''}
                  </p>
                </div>

                <div className="grid gap-1 text-right text-[0.72rem] uppercase tracking-[0.08em] text-ot-muted max-[720px]:text-left">
                  <span>created {formatTimestamp(job.created_at)}</span>
                  <span>heartbeat {formatTimestamp(job.heartbeat_at)}</span>
                  <span>finished {formatTimestamp(job.finished_at)}</span>
                </div>
              </div>

              {job.error_message ? (
                <p className="m-0 border-2 border-ot-red bg-[color-mix(in_srgb,var(--color-ot-red)_6%,var(--color-ot-surface))] px-3 py-3 text-[0.76rem] leading-[1.5] text-ot-red">
                  {job.error_message}
                </p>
              ) : null}
            </article>
          ))
        )}
      </div>
    </section>
  )
}
