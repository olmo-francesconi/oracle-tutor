import { formatTimestamp } from '../lib/format'
import type { SemanticDatasetSummary } from '../types/api'
import { StatusBadge } from './StatusBadge'

type Props = {
  datasets: SemanticDatasetSummary[]
  loading: boolean
}

function DatasetTableEmpty() {
  return (
    <div className="grid max-w-[34rem] gap-2">
      <p className="eyebrow">Empty</p>
      <p className="m-0 font-display text-[1.55rem] font-black uppercase leading-[0.95] tracking-[-0.02em] text-ot-ink">
        No datasets built.
      </p>
      <p className="m-0 text-[0.8rem] leading-[1.55] text-ot-muted">
        Run <code className="rounded-none bg-ot-bg px-1 text-ot-ink">uv run python -m scripts.build_dataset</code> from <code className="rounded-none bg-ot-bg px-1 text-ot-ink">backend/</code> to build one.
      </p>
    </div>
  )
}

export function DatasetTable({ datasets, loading }: Props) {
  return (
    <section className="grid gap-0 border-2 border-ot-ink bg-ot-surface" aria-label="Datasets">
      <div className="overflow-x-auto max-[900px]:hidden">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="border-b-2 border-ot-ink bg-ot-bg text-left">
              {['Dataset', 'Status', 'Augmentation', 'Created'].map((label) => (
                <th key={label} className="px-4 py-3 font-display text-[0.92rem] font-black uppercase tracking-[0.02em]">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className="animate-ot-loading-pulse px-4 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">
                  Loading…
                </td>
              </tr>
            ) : datasets.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-5 py-8">
                  <DatasetTableEmpty />
                </td>
              </tr>
            ) : (
              datasets.map((ds) => (
                <tr key={ds.id} className="border-b-2 border-ot-line align-top transition-colors duration-150 hover:bg-ot-bg last:border-b-0">
                  <td className="px-4 py-4">
                    <div className="grid gap-1">
                      <span className="break-words font-display text-[1.25rem] font-black uppercase leading-none tracking-[-0.02em]">
                        {ds.slug}
                      </span>
                      {ds.source_semantic_data_version != null && (
                        <span className="text-[0.72rem] uppercase tracking-[0.08em] text-ot-muted">
                          v{ds.source_semantic_data_version}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <StatusBadge status={ds.status} />
                    {ds.error_message ? (
                      <p className="m-0 break-words pt-2 text-[0.72rem] leading-[1.45] text-ot-red">{ds.error_message}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-4 text-[0.76rem] uppercase tracking-[0.08em] text-ot-muted">
                    {ds.augmentation_mode}
                  </td>
                  <td className="px-4 py-4 text-[0.76rem] uppercase tracking-[0.08em] text-ot-muted">
                    {formatTimestamp(ds.created_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="hidden max-[900px]:grid">
        {loading ? (
          <div className="animate-ot-loading-pulse px-5 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">Loading…</div>
        ) : datasets.length === 0 ? (
          <div className="px-5 py-8">
            <DatasetTableEmpty />
          </div>
        ) : (
          datasets.map((ds) => (
            <article key={ds.id} className="grid gap-3 border-b-2 border-ot-line px-5 py-4 last:border-b-0">
              <div className="flex items-start justify-between gap-2">
                <span className="font-display text-[1.2rem] font-black uppercase leading-none tracking-[-0.02em]">{ds.slug}</span>
                <span className="shrink-0"><StatusBadge status={ds.status} /></span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-[0.72rem] uppercase tracking-[0.08em] text-ot-muted">
                <div>
                  <span className="block text-ot-ink">Created</span>
                  {formatTimestamp(ds.created_at)}
                </div>
                <div>
                  <span className="block text-ot-ink">Augmentation</span>
                  {ds.augmentation_mode}
                </div>
              </div>
              {ds.error_message ? (
                <p className="m-0 border-2 border-ot-red px-3 py-3 text-[0.76rem] leading-[1.5] text-ot-red">{ds.error_message}</p>
              ) : null}
            </article>
          ))
        )}
      </div>
    </section>
  )
}
