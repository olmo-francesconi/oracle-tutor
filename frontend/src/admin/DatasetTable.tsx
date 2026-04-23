import { formatTimestamp } from '../lib/format'
import type { SemanticDatasetSummary } from '../types/api'
import { StatusBadge } from './StatusBadge'

type Props = {
  datasets: SemanticDatasetSummary[]
  loading: boolean
}

export function DatasetTable({ datasets, loading }: Props) {
  return (
    <section className="grid gap-0 border-2 border-ot-ink bg-ot-surface">
      <div className="border-b-2 border-ot-ink px-5 py-4">
        <p className="eyebrow">Datasets</p>
        <h2 className="m-0 pt-2 font-display text-[2.1rem] font-black uppercase leading-[0.9] tracking-[-0.03em]">
          Training datasets
        </h2>
      </div>

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
                <td colSpan={4} className="px-4 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">
                  No datasets built yet.
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
          <div className="px-5 py-8 text-[0.78rem] uppercase tracking-[0.08em] text-ot-muted">No datasets built yet.</div>
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
