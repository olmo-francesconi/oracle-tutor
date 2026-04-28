import type { ChangeEvent } from 'react'
import { FilterChecklist } from './FilterChecklist'
import {
  CARD_TYPE_OPTIONS,
  COLOR_OPTIONS,
  FORMAT_OPTIONS,
  RARITY_OPTIONS,
  cycleColorFeature,
  cycleMatchMode,
  hasActiveFilters,
  normalizeFilterState,
  toggleFilterColor,
  toggleFilterRarity,
} from '../lib/filters'
import type { FilterState } from '../types/api'

interface FilterBarProps {
  filters: FilterState
  onChange: (filters: FilterState) => void
  onClear: () => void
}

function toTitleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

function getMatchModeLabel(matchMode: FilterState['matchMode']): string {
  if (matchMode === 'exact') return 'Exact'
  if (matchMode === 'at_most') return 'At Most'
  return 'At Least'
}

function getColorFeatureLabel(colorFeature: FilterState['colorFeature']): string {
  return colorFeature === 'colors' ? 'Cost' : 'Identity'
}

export function FilterBar({ filters, onChange, onClear }: FilterBarProps) {
  const hasFilters = hasActiveFilters(filters)

  const handleNumberChange =
    (key: 'cmcMin' | 'cmcMax') =>
    (event: ChangeEvent<HTMLInputElement>) => {
      const nextValue = event.target.value

      onChange(
        normalizeFilterState({
          ...filters,
          [key]: nextValue === '' ? undefined : Number(nextValue),
        })
      )
    }

  return (
    <section
      className="relative z-20 grid gap-4 border-b-2 border-ot-ink bg-ot-surface px-4 pb-4 pl-6 pr-14 pt-3 md:px-6 md:pl-[38px] md:pr-6 lg:pr-[11.5rem]"
      aria-label="Search filters"
    >
      <div className="grid content-start justify-start gap-x-8 gap-y-4 md:grid-cols-[repeat(2,max-content)] md:items-start lg:grid-cols-[repeat(3,max-content)]">
          <div className="grid gap-1.5">
            <p className="m-0 text-[0.625rem] font-display font-black uppercase tracking-[0.14em] text-ot-muted">
              Color
            </p>
            <div className="grid gap-2">
              <div className="flex flex-wrap items-center gap-2">
                {COLOR_OPTIONS.map((option) => {
                  const isSelected = filters.colors?.includes(option.value) ?? false

                  return (
                    <button
                      key={option.value}
                      type="button"
                      className="flex h-10 w-10 items-center justify-center border-2 text-[0.6875rem] font-black transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none"
                      style={
                        isSelected
                          ? { backgroundColor: option.bg, borderColor: option.border, color: option.textOnSelected }
                          : { backgroundColor: option.paleBg, borderColor: option.border, color: option.border }
                      }
                      title={option.label}
                      aria-pressed={isSelected}
                      onClick={() => onChange(toggleFilterColor(filters, option.value))}
                    >
                      {option.value}
                    </button>
                  )
                })}
              </div>

              <div className="grid grid-cols-[repeat(6,40px)] gap-2">
                <button
                  type="button"
                  className={[
                    'col-span-3 min-h-10 min-w-0 border-2 px-3 text-left font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
                    filters.matchMode && filters.matchMode !== 'at_least'
                      ? 'border-ot-ink bg-ot-ink text-ot-bg'
                      : 'border-ot-line bg-transparent text-ot-ink hover:border-ot-ink',
                  ].join(' ')}
                  onClick={() => onChange(cycleMatchMode(filters))}
                >
                  {getMatchModeLabel(filters.matchMode)}
                </button>

                <button
                  type="button"
                  className={[
                    'col-span-3 min-h-10 min-w-0 border-2 px-3 text-left font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
                    filters.colorFeature === 'colors'
                      ? 'border-ot-ink bg-ot-ink text-ot-bg'
                      : 'border-ot-line bg-transparent text-ot-ink hover:border-ot-ink',
                  ].join(' ')}
                  onClick={() => onChange(cycleColorFeature(filters))}
                >
                  {getColorFeatureLabel(filters.colorFeature)}
                </button>
              </div>
            </div>
          </div>

          <div className="grid gap-1.5">
            <p className="m-0 text-[0.625rem] font-display font-black uppercase tracking-[0.14em] text-ot-muted">
              Rarities and CMC
            </p>
            <div className="grid gap-2">
              <div className="grid grid-cols-[repeat(4,40px)] gap-2">
                {RARITY_OPTIONS.map((option) => {
                  const isSelected = filters.rarities?.includes(option.value) ?? false

                  return (
                    <button
                      key={option.value}
                      type="button"
                      className="flex h-10 w-10 items-center justify-center border-2 text-[0.6875rem] font-black transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none"
                      style={
                        isSelected
                          ? { backgroundColor: option.bg, borderColor: option.border, color: option.textOnSelected }
                          : { backgroundColor: option.paleBg, borderColor: option.border, color: option.border }
                      }
                      title={option.label}
                      aria-pressed={isSelected}
                      onClick={() => onChange(toggleFilterRarity(filters, option.value))}
                    >
                      {option.short}
                    </button>
                  )
                })}
              </div>

              <div className="flex min-h-10 w-[184px] items-center border-2 border-ot-ink bg-ot-bg">
                <span className="px-2 font-display text-[0.625rem] font-black uppercase tracking-[0.14em] text-ot-muted">
                  CMC
                </span>
                <input
                  type="number"
                  inputMode="numeric"
                  min="0"
                  max="20"
                  placeholder="0"
                  value={filters.cmcMin ?? ''}
                  onChange={handleNumberChange('cmcMin')}
                  className="h-full min-w-0 flex-1 border-0 bg-transparent px-1 text-center text-sm text-ot-ink outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                  aria-label="Minimum mana value"
                />
                <div className="h-4 w-px bg-ot-line" aria-hidden="true" />
                <input
                  type="number"
                  inputMode="numeric"
                  min="0"
                  max="20"
                  placeholder="∞"
                  value={filters.cmcMax ?? ''}
                  onChange={handleNumberChange('cmcMax')}
                  className="h-full min-w-0 flex-1 border-0 bg-transparent px-1 text-center text-sm text-ot-ink outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                  aria-label="Maximum mana value"
                />
              </div>
            </div>
          </div>

        <div className="grid gap-1.5 md:col-span-2 lg:col-span-1">
          <p className="m-0 text-[0.625rem] font-display font-black uppercase tracking-[0.14em] text-ot-muted">
            Type and format
          </p>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <FilterChecklist
              label="Card type filter"
              options={CARD_TYPE_OPTIONS}
              value={filters.cardType}
              placeholder="Type"
              minWidthClassName="md:min-w-[184px]"
              onChange={(nextValue) => onChange(normalizeFilterState({ ...filters, cardType: nextValue }))}
              formatOptionLabel={toTitleCase}
            />

            <FilterChecklist
              label="Format filter"
              options={FORMAT_OPTIONS}
              value={filters.format}
              placeholder="Format"
              minWidthClassName="md:min-w-[184px]"
              onChange={(nextValue) => onChange(normalizeFilterState({ ...filters, format: nextValue }))}
              formatOptionLabel={toTitleCase}
            />
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute right-4 top-3 flex justify-end md:bottom-4 md:right-6 md:top-auto">
        <button
          type="button"
          className={[
            'pointer-events-auto flex h-10 w-10 items-center justify-center border-2 transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none md:min-h-10 md:w-auto md:px-3 md:font-display md:text-[0.6875rem] md:font-black md:uppercase md:tracking-[0.12em]',
            hasFilters
              ? 'cursor-pointer border-ot-ink bg-transparent text-ot-ink hover:bg-ot-ink hover:text-ot-bg'
              : 'cursor-not-allowed border-ot-line bg-transparent text-ot-muted',
          ].join(' ')}
          onClick={onClear}
          disabled={!hasFilters}
          aria-label="Clear filters"
        >
          <span className="md:hidden" aria-hidden="true">
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="square">
              <path d="M2 3h12L9.5 8v4.25l-3 1V8L2 3Z" />
              <path d="M3 13 13 3" />
            </svg>
          </span>
          <span className="hidden md:inline">Clear filters</span>
        </button>
      </div>
    </section>
  )
}
