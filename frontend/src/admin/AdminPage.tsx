import { useCallback, useMemo, useState } from 'react'
import { useIsFetching, useQueryClient } from '@tanstack/react-query'
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
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('models')

  const modelsQuery = useAdminModels()
  const datasetsQuery = useAdminDatasets()

  const models = useMemo(() => modelsQuery.data ?? [], [modelsQuery.data])
  const datasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])

  const loading = modelsQuery.isLoading || datasetsQuery.isLoading
  const refreshing = useIsFetching({ queryKey: ['admin'] }) > 0

  const error = firstErrorMessage([modelsQuery.error, datasetsQuery.error])

  const handleRefresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['admin'] })
  }, [queryClient])

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
          <div className="flex items-start justify-between gap-4 max-[920px]:flex-col max-[920px]:items-stretch">
            <div className="grid gap-2">
              <p className="eyebrow">Semantic Registry / Admin</p>
              <h1 className="m-0 max-w-[11ch] font-display text-[clamp(3.8rem,9vw,7rem)] font-black uppercase leading-[0.84] tracking-[-0.04em]">
                Registry board
              </h1>
            </div>

            <div className="grid w-full max-w-[320px] min-w-0 gap-0 self-start border-2 border-ot-ink bg-ot-surface max-[920px]:max-w-none">
              <a
                href="/"
                className="border-b-2 border-ot-ink px-4 py-3 font-display text-[1.1rem] font-black uppercase tracking-[-0.02em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg"
              >
                Return to search
              </a>
              {onLogout ? (
                <button
                  type="button"
                  onClick={onLogout}
                  className="border-b-2 border-ot-ink px-4 py-3 text-left font-display text-[1.1rem] font-black uppercase tracking-[-0.02em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-red hover:text-ot-bg"
                >
                  Sign out
                </button>
              ) : null}
              <button
                type="button"
                onClick={handleRefresh}
                className="border-b-2 border-ot-ink px-4 py-3 text-left font-display text-[1.1rem] font-black uppercase tracking-[-0.02em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg active:opacity-80"
              >
                {refreshing ? 'Refreshing…' : 'Refresh board'}
              </button>
              <div className="grid grid-cols-3">
                <div className="overflow-hidden border-r-2 border-ot-ink px-2 py-2">
                  <p className="eyebrow">Models</p>
                  <p className="m-0 pt-1 font-display text-2xl font-black uppercase leading-none">{models.length}</p>
                </div>
                <div className="overflow-hidden border-r-2 border-ot-ink px-2 py-2">
                  <p className="eyebrow">Datasets</p>
                  <p className="m-0 pt-1 font-display text-2xl font-black uppercase leading-none">{datasets.length}</p>
                </div>
                <div className="overflow-hidden px-2 py-2">
                  <p className="eyebrow">Pulse</p>
                  <p className="m-0 pt-1 font-display text-base font-black uppercase leading-none">
                    {refreshing ? 'syncing' : 'steady'}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </header>

        {error ? (
          <div className="mt-4 border-2 border-ot-red bg-ot-surface px-4 py-3 text-[0.78rem] uppercase tracking-[0.08em] text-ot-red">
            {error}
          </div>
        ) : null}

        <div className="flex gap-0 border-b-2 border-ot-ink pt-6">
          {(['models', 'datasets'] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={[
                'px-5 py-3 font-display text-[0.98rem] font-black uppercase tracking-[-0.02em] transition-colors duration-150',
                tab === t
                  ? 'border-2 border-b-0 border-ot-ink bg-ot-surface'
                  : 'border-2 border-transparent text-ot-muted hover:text-ot-ink',
              ].join(' ')}
            >
              {t}
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
