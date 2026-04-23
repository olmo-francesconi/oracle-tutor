import { formatBytes, formatTimestamp } from '../lib/format'
import type { SemanticJobSummary, SemanticModelSummary } from '../types/api'
import { StatusBadge } from './StatusBadge'

type Props = {
  models: SemanticModelSummary[]
  loading: boolean
  submitting: boolean
  activePromoteJob: SemanticJobSummary | null
  onPromote: (modelId: number) => void
}

export function ModelTable({ models, loading, submitting, activePromoteJob, onPromote }: Props) {
  return (
    <section className="grid gap-0 border-2 border-ot-ink bg-ot-surface">
      <div className="border-b-2 border-ot-ink px-5 py-4">
        <p className="eyebrow">Models</p>
        <h2 className="m-0 pt-2 font-display text-[2.1rem] font-black uppercase leading-[0.9] tracking-[-0.03em]">
          Available candidates
        </h2>
      </div>

      <div className="overflow-x-auto max-[900px]:hidden">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="border-b-2 border-ot-ink bg-ot-bg text-left">
              {['Model', 'Status', 'Created', 'Artifact', 'Action'].map((label) => (
                <th key={label} className="px-4 py-3 font-display text-[0.92rem] font-black uppercase tracking-[0.02em]">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="animate-ot-loading-pulse px-4 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">
                  Loading…
                </td>
              </tr>
            ) : models.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">
                  No models registered yet.
                </td>
              </tr>
            ) : (
              models.map((model) => {
                const blockedByPromoteLane = !!activePromoteJob && activePromoteJob.model_id !== model.id
                const disablePromote = submitting || model.is_active || model.status === 'embedding' || blockedByPromoteLane

                return (
                  <tr key={model.id} className="border-b-2 border-ot-line align-top transition-colors duration-150 hover:bg-ot-bg last:border-b-0">
                    <td className="px-4 py-4">
                      <div className="grid gap-1">
                        <span className="break-words font-display text-[1.25rem] font-black uppercase leading-none tracking-[-0.02em]">
                          {model.slug}
                        </span>
                        <span className="text-[0.72rem] uppercase tracking-[0.08em] text-ot-muted">
                          {model.base_model}
                        </span>
                        {model.is_active ? (
                          <span className="inline-block w-fit border-2 border-ot-ink bg-ot-red px-2 py-1 text-[0.68rem] uppercase tracking-[0.08em] text-ot-bg">
                            Active
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <StatusBadge status={model.status} />
                      {model.error_message ? (
                        <p className="m-0 break-words pt-2 text-[0.72rem] leading-[1.45] text-ot-red">{model.error_message}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-4 text-[0.76rem] uppercase tracking-[0.08em] text-ot-muted">
                      <div>{formatTimestamp(model.created_at)}</div>
                      {model.activated_at ? <div className="pt-2 text-ot-ink">live {formatTimestamp(model.activated_at)}</div> : null}
                    </td>
                    <td className="px-4 py-4 text-[0.76rem] uppercase tracking-[0.08em] text-ot-muted">
                      <div>{formatBytes(model.artifact_size_bytes)}</div>
                      <div className="pt-2 text-ot-ink">dim {model.embedding_dim}</div>
                    </td>
                    <td className="px-4 py-4">
                      <button
                        type="button"
                        disabled={disablePromote}
                        onClick={() => onPromote(model.id)}
                        className="min-h-12 cursor-pointer border-2 border-ot-ink bg-ot-bg px-4 py-2 font-display text-[0.98rem] font-black uppercase tracking-[-0.02em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg active:opacity-80 disabled:cursor-not-allowed disabled:border-ot-line disabled:bg-ot-bg disabled:text-ot-muted"
                      >
                        {model.is_active ? 'Live now' : blockedByPromoteLane ? 'Lane locked' : 'Promote'}
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="hidden max-[900px]:grid">
        {loading ? (
          <div className="animate-ot-loading-pulse px-5 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">Loading…</div>
        ) : models.length === 0 ? (
          <div className="px-5 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">
            No models registered yet.
          </div>
        ) : (
          models.map((model) => {
            const blockedByPromoteLane = !!activePromoteJob && activePromoteJob.model_id !== model.id
            const disablePromote = submitting || model.is_active || model.status === 'embedding' || blockedByPromoteLane

            return (
              <article key={model.id} className="grid gap-4 border-b-2 border-ot-line px-5 py-4 last:border-b-0">
                <div className="grid gap-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="grid min-w-0 gap-1">
                      <span className="break-words font-display text-[1.25rem] font-black uppercase leading-none tracking-[-0.02em]">
                        {model.slug}
                      </span>
                      <span className="break-words text-[0.72rem] uppercase tracking-[0.08em] text-ot-muted">
                        {model.base_model}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge status={model.status} />
                      {model.is_active ? (
                        <span className="inline-block border-2 border-ot-ink bg-ot-red px-2 py-1 text-[0.68rem] uppercase tracking-[0.08em] text-ot-bg">
                          Active
                        </span>
                      ) : null}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-[0.74rem] uppercase tracking-[0.08em] text-ot-muted max-[420px]:grid-cols-1">
                    <div className="grid gap-1 border-2 border-ot-line bg-ot-bg px-3 py-3">
                      <span className="eyebrow">Created</span>
                      <span>{formatTimestamp(model.created_at)}</span>
                      {model.activated_at ? <span className="text-ot-ink">live {formatTimestamp(model.activated_at)}</span> : null}
                    </div>
                    <div className="grid gap-1 border-2 border-ot-line bg-ot-bg px-3 py-3">
                      <span className="eyebrow">Artifact</span>
                      <span>{formatBytes(model.artifact_size_bytes)}</span>
                      <span className="text-ot-ink">dim {model.embedding_dim}</span>
                    </div>
                  </div>

                  {model.error_message ? (
                    <p className="m-0 border-2 border-ot-red bg-[color-mix(in_srgb,var(--color-ot-red)_6%,var(--color-ot-surface))] px-3 py-3 text-[0.74rem] leading-[1.5] text-ot-red">
                      {model.error_message}
                    </p>
                  ) : null}
                </div>

                <button
                  type="button"
                  disabled={disablePromote}
                  onClick={() => onPromote(model.id)}
                  className="min-h-12 cursor-pointer border-2 border-ot-ink bg-ot-bg px-4 py-2 font-display text-[0.98rem] font-black uppercase tracking-[-0.02em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg active:opacity-80 disabled:cursor-not-allowed disabled:border-ot-line disabled:bg-ot-bg disabled:text-ot-muted"
                >
                  {model.is_active ? 'Live now' : blockedByPromoteLane ? 'Lane locked' : 'Promote'}
                </button>
              </article>
            )
          })
        )}
      </div>
    </section>
  )
}
