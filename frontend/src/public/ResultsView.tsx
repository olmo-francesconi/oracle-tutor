import { AbilityTuner } from '../components/AbilityTuner'
import { FilterBar } from '../components/FilterBar'
import { ResultsGrid } from '../components/ResultsGrid'
import { SearchBox } from '../components/SearchBox/SearchBox'
import { SymbolText } from '../components/SymbolText'
import { SearchErrorPanel } from '../components/errors/SearchErrorPanel'
import type { CardAbility, CardMatch, FilterState, SimilarCard } from '../types/api'
import type { AbilityChoice, AbilitySelection, SearchShellState } from '../types/ui'

type PinnedSummary = {
  oracleText: string | null
  abilities: CardAbility[]
} | null

type Props = {
  state: SearchShellState
  showFilters: boolean
  activeFilterCount: number
  lastTextQuery?: string | null
  pinnedSummary?: PinnedSummary
  abilitySelection: AbilitySelection
  onCycleAbility: (abilityIx: number) => void
  onSetAbilities: (abilityIxs: number[], choice: AbilityChoice | null) => void
  onResetAbilities: () => void
  onDraftChange: (value: string) => void
  onSubmit: (value?: string) => void
  onCardSelect: (card: CardMatch) => void
  onReset: () => void
  onToggleFilters: () => void
  onFiltersChange: (filters: FilterState) => void
  onClearFilters: () => void
  onLoadMore: () => void
  onCardOpen: (card: SimilarCard) => void
  onTitleClick?: () => void
  onRestoreTextQuery?: () => void
}

export function ResultsView({
  state,
  showFilters,
  activeFilterCount,
  lastTextQuery,
  pinnedSummary,
  abilitySelection,
  onCycleAbility,
  onSetAbilities,
  onResetAbilities,
  onDraftChange,
  onSubmit,
  onCardSelect,
  onReset,
  onToggleFilters,
  onFiltersChange,
  onClearFilters,
  onLoadMore,
  onCardOpen,
  onTitleClick,
  onRestoreTextQuery,
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
                <span
                  className={[
                    'flex h-4 w-4 shrink-0 items-center justify-center font-display text-[0.5625rem] font-black max-[720px]:hidden',
                    showFilters ? 'bg-ot-bg text-ot-ink' : 'bg-ot-ink text-ot-bg',
                  ].join(' ')}
                >
                  {activeFilterCount}
                </span>
              )}
            </button>
          </header>

          {state.pinnedCard ? (
            <section
              className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-x-10 gap-y-3 border-b-2 border-ot-ink bg-ot-bg px-6 pb-5 pl-[38px] pr-6 pt-4 max-[860px]:grid-cols-1 max-[860px]:gap-y-3 max-[720px]:px-4 max-[720px]:pb-4 max-[720px]:pl-6 max-[720px]:pt-[14px]"
              aria-label="Results summary"
            >
              <div className="grid max-w-[min(34rem,100%)] content-start gap-1 max-[720px]:gap-0.5">
                {lastTextQuery && onRestoreTextQuery ? (
                  <button
                    type="button"
                    onClick={onRestoreTextQuery}
                    className="m-0 inline-flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 pb-1 text-left lowercase tracking-[0.04em] text-ot-muted transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:text-ot-red motion-reduce:transition-none"
                    style={{ fontSize: '0.78rem' }}
                  >
                    <svg viewBox="0 0 16 16" className="h-2.5 w-2.5" fill="currentColor" aria-hidden="true">
                      <path d="M13 8H3.5L7 11.5l-1 1L1 7.5 6 2.5l1 1L3.5 7H13z" />
                    </svg>
                    <span>back to "{lastTextQuery}"</span>
                  </button>
                ) : null}
                <p className="eyebrow">Similar to</p>
                {onTitleClick ? (
                  <button
                    type="button"
                    onClick={onTitleClick}
                    aria-label={`Open detail for ${state.submittedQuery ?? 'pinned card'}`}
                    className="m-0 inline cursor-pointer border-0 bg-transparent p-0 text-left font-display text-[2.4rem] font-black uppercase leading-[0.9] tracking-[-0.02em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:text-ot-red motion-reduce:transition-none"
                  >
                    {state.submittedQuery}
                  </button>
                ) : (
                  <h2 className="m-0 font-display text-[2.4rem] font-black uppercase leading-[0.9] tracking-[-0.02em]">
                    {state.submittedQuery}
                  </h2>
                )}
              </div>

              <div className="grid content-start self-stretch border-l-2 border-ot-ink pl-8 max-[860px]:border-l-0 max-[860px]:border-t-2 max-[860px]:pl-0 max-[860px]:pt-3">
                {pinnedSummary?.abilities.length ? (
                  <AbilityTuner
                    abilities={pinnedSummary.abilities}
                    selection={abilitySelection}
                    onCycle={onCycleAbility}
                    onSet={onSetAbilities}
                    onReset={onResetAbilities}
                  />
                ) : pinnedSummary?.oracleText ? (
                  <div className="whitespace-pre-line text-[0.85rem] leading-[1.55] text-ot-ink">
                    <SymbolText text={pinnedSummary.oracleText} />
                  </div>
                ) : pinnedSummary === null ? null : (
                  <p className="m-0 text-[0.85rem] italic text-ot-muted">No oracle text on file.</p>
                )}
              </div>
            </section>
          ) : null}

          {showFilters && (
            <FilterBar filters={state.filters} onChange={onFiltersChange} onClear={onClearFilters} />
          )}
        </div>

        <section
          className="px-6 pb-14 pl-[38px] pr-6 pt-6 max-[720px]:px-4 max-[720px]:pl-6"
          aria-label="Results state"
        >
          {state.isLoading ? (
            <div className="grid gap-4" aria-hidden="true">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 min-[1500px]:grid-cols-6">
                {Array.from({ length: 10 }, (_, index) => (
                  <span
                    key={index}
                    className="block aspect-[63/88] w-full animate-ot-loading-pulse rounded-xl bg-[color:color-mix(in_srgb,var(--color-ot-line)_72%,var(--color-ot-bg))]"
                  />
                ))}
              </div>
            </div>
          ) : null}
          {!state.isLoading && state.error ? <SearchErrorPanel message={state.error} /> : null}
          {!state.isLoading && !state.error && state.results.length === 0 ? (
            <div className="grid max-w-[28rem] gap-2">
              <p className="eyebrow">No matches</p>
              <p className="m-0 font-display text-[1.55rem] font-black uppercase leading-[0.95] tracking-[-0.02em] text-ot-ink">
                Nothing landed for {state.submittedQuery ? `"${state.submittedQuery}"` : 'this search'}.
              </p>
              <p className="m-0 text-[0.85rem] leading-[1.55] text-ot-muted">
                Try fewer filters, or describe the effect in plain language ("untap when blocked", "exile from graveyard").
              </p>
            </div>
          ) : null}
          {state.results.length > 0 ? (
            <ResultsGrid
              cards={state.results}
              hasMore={state.hasMore}
              isLoadingMore={state.isLoadingMore}
              onLoadMore={onLoadMore}
              onCardOpen={onCardOpen}
            />
          ) : null}
        </section>
      </div>
    </>
  )
}
