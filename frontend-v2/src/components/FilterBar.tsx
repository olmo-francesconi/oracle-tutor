import type { ChangeEvent } from 'react'
import {
  CARD_TYPE_OPTIONS,
  COLOR_OPTIONS,
  FORMAT_OPTIONS,
  RARITY_OPTIONS,
  cycleColorFeature,
  cycleMatchMode,
  getActiveFilterCount,
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
  const activeFilterCount = getActiveFilterCount(filters)
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

  const handleSelectChange =
    (key: 'cardType' | 'format') =>
    (event: ChangeEvent<HTMLSelectElement>) => {
      const nextValue = event.target.value

      onChange(
        normalizeFilterState({
          ...filters,
          [key]: nextValue || undefined,
        })
      )
    }

  return (
    <section
      className="relative z-20 grid gap-3 border-b-2 border-ot-ink bg-ot-surface px-6 pb-4 pl-[38px] pr-6 pt-3 max-[720px]:gap-4 max-[720px]:px-4 max-[720px]:pl-6"
      aria-label="Search filters"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 max-[560px]:grid max-[560px]:grid-cols-1 max-[560px]:items-start">
        <div className="grid gap-0.5">
          <p className="eyebrow">Filters</p>
          <p className="m-0 text-[0.6875rem] uppercase tracking-[0.12em] text-ot-muted">
            {hasFilters ? `${activeFilterCount} active` : 'Refine by color, type, cost, and legality.'}
          </p>
        </div>
        <button
          type="button"
          className={[
            'min-h-10 border-2 px-3 font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none max-[560px]:w-full',
            hasFilters
              ? 'cursor-pointer border-ot-ink bg-transparent text-ot-ink hover:bg-ot-ink hover:text-ot-bg'
              : 'cursor-not-allowed border-ot-line bg-transparent text-ot-muted',
          ].join(' ')}
          onClick={onClear}
          disabled={!hasFilters}
        >
          Clear filters
        </button>
      </div>

      <div className="grid gap-3">
        <div className="grid gap-1.5">
          <p className="m-0 text-[0.625rem] font-display font-black uppercase tracking-[0.14em] text-ot-muted">
            Colors and rarity
          </p>
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
        </div>

        <div className="grid gap-1.5">
          <p className="m-0 text-[0.625rem] font-display font-black uppercase tracking-[0.14em] text-ot-muted">
            Match and mana value
          </p>
          <div className="grid grid-cols-[repeat(3,minmax(0,1fr))] gap-2 max-[640px]:grid-cols-1">
            <button
              type="button"
              className={[
                'min-h-10 min-w-0 border-2 px-3 font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
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
                'min-h-10 min-w-0 border-2 px-3 font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none',
                filters.colorFeature === 'colors'
                  ? 'border-ot-ink bg-ot-ink text-ot-bg'
                  : 'border-ot-line bg-transparent text-ot-ink hover:border-ot-ink',
              ].join(' ')}
              onClick={() => onChange(cycleColorFeature(filters))}
            >
              {getColorFeatureLabel(filters.colorFeature)}
            </button>

            <div className="flex min-h-10 items-center border-2 border-ot-ink bg-ot-bg">
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

        <div className="grid gap-1.5">
          <p className="m-0 text-[0.625rem] font-display font-black uppercase tracking-[0.14em] text-ot-muted">
            Card shape
          </p>
          <div className="grid grid-cols-2 gap-2 max-[560px]:grid-cols-1">
            <select
              value={filters.cardType ?? ''}
              onChange={handleSelectChange('cardType')}
              className="min-h-10 min-w-0 border-2 border-ot-ink bg-white px-3 font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] text-ot-ink outline-none"
              aria-label="Card type filter"
            >
              <option value="">Type</option>
              {CARD_TYPE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {toTitleCase(option)}
                </option>
              ))}
            </select>

            <select
              value={filters.format ?? ''}
              onChange={handleSelectChange('format')}
              className="min-h-10 min-w-0 border-2 border-ot-ink bg-white px-3 font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] text-ot-ink outline-none"
              aria-label="Format filter"
            >
              <option value="">Format</option>
              {FORMAT_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {toTitleCase(option)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
    </section>
  )
}
