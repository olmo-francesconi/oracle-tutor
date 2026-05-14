import { useMemo, useState } from 'react'
import { useAdminDatasets, useAdminModels } from './adminQueries'
import { DatasetTable } from './DatasetTable'
import { ModelTable } from './ModelTable'

type Tab = 'models' | 'datasets'

type AdminPageProps = {
  onLogout?: () => void
}

function firstErrorMessage(errors: (Error | null | undefined)[]): string | null {
  for (const error of errors) {
    if (error) return error.message
  }
  return null
}

export function AdminPage({ onLogout }: AdminPageProps) {
  const [tab, setTab] = useState<Tab>('models')

  const modelsQuery = useAdminModels()
  const datasetsQuery = useAdminDatasets()

  const models = useMemo(() => modelsQuery.data ?? [], [modelsQuery.data])
  const datasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])

  const loading = modelsQuery.isLoading || datasetsQuery.isLoading
  const error = firstErrorMessage([modelsQuery.error, datasetsQuery.error])

  return (
    <main className="relative min-h-screen overflow-x-clip bg-ot-bg text-ot-ink">
      <div className="fixed inset-y-0 left-0 z-10 w-1.5 bg-ot-red" aria-hidden="true" />
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        aria-hidden="true"
        style={{
          backgroundImage:
            'repeating-linear-gradient(to bottom, transparent 0, transparent 70px, rgba(17,17,17,0.05) 70px, rgba(17,17,17,0.05) 72px)',
        }}
      />

      <div className="relative z-20 mx-auto flex min-h-screen w-full max-w-[1560px] flex-col px-6 pb-10 pl-11 pt-6 max-[920px]:px-4 max-[920px]:pl-[30px]">
        <header className="grid gap-4 border-b-2 border-ot-ink pb-5 max-[920px]:gap-3">
          <div className="flex items-start justify-between gap-6 max-[920px]:flex-col max-[920px]:items-start max-[920px]:gap-3">
            <div className="grid gap-2">
              <p className="eyebrow">Semantic Registry / Admin</p>
              <h1 className="m-0 max-w-[11ch] font-display text-[clamp(3.8rem,9vw,7rem)] font-black uppercase leading-[0.84] tracking-[-0.04em]">
                Registry board
              </h1>
            </div>

            <nav
              aria-label="Admin actions"
              className="flex items-center gap-4 self-end text-[0.78rem] uppercase tracking-[0.12em] text-ot-muted max-[920px]:self-start"
            >
              <a
                href="/"
                className="font-display font-black tracking-[0.06em] text-ot-ink underline decoration-ot-ink/30 decoration-2 underline-offset-[6px] transition-colors duration-150 hover:text-ot-red hover:decoration-ot-red motion-reduce:transition-none"
              >
                Return to search
              </a>
              {onLogout ? (
                <>
                  <span aria-hidden="true" className="text-ot-muted">·</span>
                  <button
                    type="button"
                    onClick={onLogout}
                    className="cursor-pointer border-0 bg-transparent p-0 font-display font-black tracking-[0.06em] text-ot-ink underline decoration-ot-ink/30 decoration-2 underline-offset-[6px] transition-colors duration-150 hover:text-ot-red hover:decoration-ot-red motion-reduce:transition-none"
                  >
                    Sign out
                  </button>
                </>
              ) : null}
            </nav>
          </div>
        </header>

        {error ? (
          <div className="mt-4 border-2 border-ot-red bg-ot-surface px-4 py-3 text-[0.78rem] uppercase tracking-[0.08em] text-ot-red">
            {error}
          </div>
        ) : null}

        <div className="flex gap-0 border-b-2 border-ot-ink pt-6">
          {(
            [
              { key: 'models', label: 'Models', count: models.length },
              { key: 'datasets', label: 'Datasets', count: datasets.length },
            ] as { key: Tab; label: string; count: number }[]
          ).map(({ key, label, count }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              aria-pressed={tab === key}
              className={[
                'flex items-baseline gap-3 px-5 py-3 font-display text-[0.98rem] font-black uppercase tracking-[0.04em] transition-colors duration-150 motion-reduce:transition-none',
                tab === key
                  ? 'border-2 border-b-0 border-ot-ink bg-ot-surface text-ot-ink'
                  : 'border-2 border-transparent text-ot-muted hover:text-ot-ink',
              ].join(' ')}
            >
              <span>{label}</span>
              <span
                className={[
                  'text-[0.72rem] tracking-[0.08em]',
                  tab === key ? 'text-ot-muted' : 'text-ot-muted/70',
                ].join(' ')}
              >
                {loading ? '—' : count}
              </span>
            </button>
          ))}
        </div>

        <div className="pt-6">
          {tab === 'models' ? (
            <ModelTable models={models} loading={loading} />
          ) : (
            <DatasetTable datasets={datasets} loading={loading} />
          )}
        </div>
      </div>
    </main>
  )
}
