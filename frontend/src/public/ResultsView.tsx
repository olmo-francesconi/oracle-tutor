import { FilterBar } from '../components/FilterBar'
import { ResultsGrid } from '../components/ResultsGrid'
import { SearchBox } from '../components/SearchBox/SearchBox'
import { SearchErrorPanel } from '../components/errors/SearchErrorPanel'
import type { CardMatch, FilterState } from '../types/api'
import type { SearchShellState } from '../types/ui'

type Props = {
  state: SearchShellState
  showFilters: boolean
  activeFilterCount: number
  onDraftChange: (value: string) => void
  onSubmit: (value?: string) => void
  onCardSelect: (card: CardMatch) => void
  onReset: () => void
  onToggleFilters: () => void
  onFiltersChange: (filters: FilterState) => void
  onClearFilters: () => void
  onLoadMore: () => void
}

export function ResultsView({
  state,
  showFilters,
  activeFilterCount,
  onDraftChange,
  onSubmit,
  onCardSelect,
  onReset,
  onToggleFilters,
  onFiltersChange,
  onClearFilters,
  onLoadMore,
}: Props) {
  return (
    <>
      <div className="fixed inset-y-0 left-0 z-20 w-1.5 bg-ot-red" aria-hidden="true" />
      <div className="relative z-10">
        <div className="sticky top-0 z-30 max-[720px]:static">
          <header className="grid min-h-[58px] grid-cols-[clamp(148px,16vw,176px)_minmax(0,1fr)_auto] items-stretch border-b-2 border-ot-ink bg-ot-bg max-[720px]:grid-cols-[auto_minmax(0,1fr)_auto]">
            <button
              type="button"
              className="flex min-w-0 cursor-pointer items-center justify-center border-0 border-r-2 border-ot-ink bg-transparent px-[18px] py-0 font-display text-[20px] font-black uppercase leading-none tracking-[-0.02em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none max-[720px]:min-h-14 max-[720px]:w-14 max-[720px]:min-w-14 max-[720px]:px-0 max-[720px]:text-[18px]"
              onClick={onReset}
            >
              <span className="max-[720px]:hidden">Oracle Tutor</span>
              <span className="hidden max-[720px]:inline">OT</span>
            </button>
            <div className="relative flex min-w-0 items-stretch bg-ot-surface">
              <SearchBox
                className="h-full self-stretch"
                value={state.draftQuery}
                onChange={onDraftChange}
                onSubmit={onSubmit}
                onCardSelect={onCardSelect}
                autoFocus={false}
                showManaRail={false}
                variant="topbar"
              />
            </div>
            <button
              type="button"
              onClick={onToggleFilters}
              className={[
                'flex shrink-0 cursor-pointer items-center justify-center gap-2 border-l-2 border-ot-ink px-4 font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none max-[720px]:w-14 max-[720px]:min-w-14 max-[720px]:px-0',
                showFilters || activeFilterCount > 0
                  ? 'bg-ot-ink text-ot-bg'
                  : 'bg-transparent text-ot-ink hover:bg-ot-ink hover:text-ot-bg',
              ].join(' ')}
              aria-expanded={showFilters}
              aria-label="Toggle filters"
            >
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 shrink-0" fill="currentColor" aria-hidden="true">
                <path d="M1 3h14l-5 5.5V13l-4 1.5V8.5L1 3Z" />
              </svg>
              <span className="max-[720px]:hidden">Filters</span>
              {activeFilterCount > 0 && (
                <span className="flex h-4 w-4 shrink-0 items-center justify-center bg-ot-red font-display text-[0.5625rem] font-black text-white max-[720px]:hidden">
                  {activeFilterCount}
                </span>
              )}
            </button>
          </header>

          <section
            className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-x-8 gap-y-[18px] border-b-2 border-ot-ink bg-ot-bg px-6 pb-[18px] pl-[38px] pr-6 pt-4 max-[720px]:grid-cols-1 max-[720px]:gap-[10px] max-[720px]:px-4 max-[720px]:pb-4 max-[720px]:pl-6 max-[720px]:pt-[14px]"
            aria-label="Results summary"
          >
            <div className="grid max-w-[min(34rem,100%)] gap-1 max-[720px]:gap-0.5">
              <p className="eyebrow">{state.pinnedCard ? 'Similar to' : 'Results'}</p>
              <h2 className="m-0 font-display text-[clamp(2.2rem,4.4vw,3.35rem)] font-black uppercase leading-[0.9] tracking-[-0.02em]">
                {state.submittedQuery}
              </h2>
            </div>
            <div className="grid min-w-[13rem] justify-items-end gap-1.5 self-center max-[720px]:min-w-0 max-[720px]:justify-items-start">
              {!state.isLoading ? (
                <span className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted" aria-live="polite">
                  {state.results.length}
                  {state.hasMore || state.isLoadingMore ? '+' : ''} cards
                </span>
              ) : null}
            </div>
          </section>

          {showFilters && (
            <FilterBar filters={state.filters} onChange={onFiltersChange} onClear={onClearFilters} />
          )}
        </div>

        <section
          className="px-6 pb-14 pl-[38px] pr-6 pt-6 max-[720px]:px-4 max-[720px]:pl-6"
          aria-label="Results state"
        >
          {state.isLoading ? (
            <div className="grid gap-3" aria-hidden="true">
              <div className="grid gap-1.5">
                <span className="block h-3 w-28 animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
                <span className="block h-8 w-[min(24rem,78vw)] animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
              </div>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(164px,1fr))] gap-3 max-[720px]:grid-cols-[repeat(auto-fill,minmax(154px,1fr))]">
                {Array.from({ length: 6 }, (_, index) => (
                  <div key={index} className="grid gap-0 border-2 border-ot-ink bg-ot-surface">
                    <span className="block h-8 animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
                    <span className="block aspect-[63/88] animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_72%,var(--color-ot-bg))]" />
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {!state.isLoading && state.error ? <SearchErrorPanel message={state.error} /> : null}
          {!state.isLoading && !state.error && state.results.length === 0 ? (
            <p className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted">
              No cards matched {state.submittedQuery ? `"${state.submittedQuery}"` : 'this search'}.
            </p>
          ) : null}
          {state.results.length > 0 ? (
            <ResultsGrid
              cards={state.results}
              hasMore={state.hasMore}
              isLoadingMore={state.isLoadingMore}
              onLoadMore={onLoadMore}
            />
          ) : null}
        </section>
      </div>
    </>
  )
}
