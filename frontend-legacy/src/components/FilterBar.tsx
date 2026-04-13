import { Funnel, ArrowCounterClockwise, X } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../lib/cn'
import type { FilterState } from '../types'

interface FilterBarProps {
  filters: FilterState
  onFilterChange: (filters: FilterState) => void
  /** 'button' = compact button that opens modal (mobile), 'inline' = full bar with all controls */
  variant?: 'button' | 'inline'
}

const COLORS = [
  { value: 'W', label: 'White',     bg: '#C8A96E', paleBg: '#F5EDD8', border: '#C8A96E', textOnSelected: '#111111' },
  { value: 'U', label: 'Blue',      bg: '#1E5094', paleBg: '#D0DDEF', border: '#1E5094', textOnSelected: '#FFFFFF' },
  { value: 'B', label: 'Black',     bg: '#111111', paleBg: '#CECAC6', border: '#111111', textOnSelected: '#FFFFFF' },
  { value: 'R', label: 'Red',       bg: '#CC1100', paleBg: '#F5D0CB', border: '#CC1100', textOnSelected: '#FFFFFF' },
  { value: 'G', label: 'Green',     bg: '#2E6840', paleBg: '#C8DACC', border: '#2E6840', textOnSelected: '#FFFFFF' },
  { value: 'C', label: 'Colorless', bg: '#7A7670', paleBg: '#E4E0DB', border: '#7A7670', textOnSelected: '#FFFFFF' },
]

const RARITIES = [
  { value: 'common',   label: 'Common',   short: 'C', bg: '#333333', paleBg: '#CECAC6', border: '#333333', textOnSelected: '#F0EDE6' },
  { value: 'uncommon', label: 'Uncommon', short: 'U', bg: '#8499A8', paleBg: '#DDE4E9', border: '#7A8C9A', textOnSelected: '#FFFFFF' },
  { value: 'rare',     label: 'Rare',     short: 'R', bg: '#C8A96E', paleBg: '#F5EDD8', border: '#B89050', textOnSelected: '#111111' },
  { value: 'mythic',   label: 'Mythic',   short: 'M', bg: '#C96428', paleBg: '#F8DBC8', border: '#B05420', textOnSelected: '#FFFFFF' },
]

const FORMATS = [
  'Standard',
  'Pioneer',
  'Modern',
  'Legacy',
  'Vintage',
  'Commander',
  'Pauper',
]

const CARD_TYPES = [
  'Creature',
  'Instant',
  'Sorcery',
  'Enchantment',
  'Artifact',
  'Planeswalker',
  'Land',
]

// --- Sub-components ---

interface FilterInputsProps {
  localFilters: FilterState
  updateFilter: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void
  handleColorClick: (color: string) => void
  isMobile?: boolean
}

function FilterInputs({ localFilters, updateFilter, handleColorClick, isMobile = false }: FilterInputsProps) {
  return (
    <div className={cn('flex flex-col items-center gap-5', isMobile && 'w-full gap-6')}>
      {/* Colors */}
      <div className="flex items-center gap-1.5">
        {COLORS.map((c) => {
          const isSelected = localFilters.colors?.includes(c.value)
          return (
            <button
              key={c.value}
              onClick={() => handleColorClick(c.value)}
              className="flex h-8 w-8 items-center justify-center border-2 text-xs font-bold transition-colors"
              style={isSelected
                ? { backgroundColor: c.bg, borderColor: c.border, color: c.textOnSelected }
                : { backgroundColor: c.paleBg, borderColor: c.border, color: c.border }
              }
              title={c.label}
            >
              {c.value}
            </button>
          )
        })}
      </div>

      {/* Match Mode + Color Feature */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => {
            const modes: ('at_least' | 'at_most' | 'exact')[] = ['at_least', 'at_most', 'exact']
            const current = localFilters.matchMode || 'at_least'
            const next = modes[(modes.indexOf(current) + 1) % modes.length]
            updateFilter('matchMode', next)
          }}
          className={cn(
            'flex h-8 w-28 shrink-0 items-center justify-center border-2 text-xs font-bold whitespace-nowrap transition-colors',
            localFilters.matchMode && localFilters.matchMode !== 'at_least'
              ? 'border-[#111111] bg-[#111111] text-white'
              : 'border-[#CCCCCC] bg-transparent text-[#111111] hover:border-[#111111]'
          )}
        >
          {localFilters.matchMode === 'exact' ? 'Exact' : localFilters.matchMode === 'at_most' ? 'At Most' : 'At Least'}
        </button>
        <button
          onClick={() => {
            const features: ('identity' | 'colors')[] = ['identity', 'colors']
            const current = localFilters.colorFeature || 'identity'
            const next = features[(features.indexOf(current) + 1) % features.length]
            updateFilter('colorFeature', next)
          }}
          className={cn(
            'flex h-8 w-28 shrink-0 items-center justify-center border-2 text-xs font-bold whitespace-nowrap transition-colors',
            localFilters.colorFeature === 'colors'
              ? 'border-[#111111] bg-[#111111] text-white'
              : 'border-[#CCCCCC] bg-transparent text-[#111111] hover:border-[#111111]'
          )}
        >
          {localFilters.colorFeature === 'colors' ? 'Cost' : 'Identity'}
        </button>
      </div>

      {/* Divider */}
      <div className="h-px w-full bg-[#E0DDD6]" />

      {/* CMC */}
      <div className="flex items-center gap-2">
        <span className="font-display text-[10px] font-bold uppercase tracking-[0.14em] text-[#7A7670]">CMC</span>
        <div className="flex items-center border-2 border-[#111111]">
          <input
            type="number"
            placeholder="0"
            min="0" max="20"
            value={localFilters.cmcMin ?? ''}
            onChange={(e) => updateFilter('cmcMin', e.target.value ? Number(e.target.value) : undefined)}
            className="h-9 w-11 bg-transparent px-1 text-center text-sm text-[#111111] outline-none [appearance:textfield] placeholder-[#ABABAB] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
          <div className="h-4 w-px bg-[#E0DDD6]" />
          <input
            type="number"
            placeholder="∞"
            min="0" max="20"
            value={localFilters.cmcMax ?? ''}
            onChange={(e) => updateFilter('cmcMax', e.target.value ? Number(e.target.value) : undefined)}
            className="h-9 w-11 bg-transparent px-1 text-center text-sm text-[#111111] outline-none [appearance:textfield] placeholder-[#ABABAB] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
        </div>
      </div>

      {/* Rarities */}
      <div className="flex items-center gap-1.5">
        {RARITIES.map((r) => {
          const isSelected = localFilters.rarities?.includes(r.value)
          return (
            <button
              key={r.value}
              onClick={() => {
                const current = localFilters.rarities ?? []
                const next = isSelected
                  ? current.filter((v) => v !== r.value)
                  : [...current, r.value]
                updateFilter('rarities', next.length ? next : undefined)
              }}
              className="flex h-8 w-8 items-center justify-center border-2 text-xs font-bold transition-colors"
              style={isSelected
                ? { backgroundColor: r.bg, borderColor: r.border, color: r.textOnSelected }
                : { backgroundColor: r.paleBg, borderColor: r.border, color: r.border }
              }
              title={r.label}
            >
              {r.short}
            </button>
          )
        })}
      </div>

      {/* Divider */}
      <div className="h-px w-full bg-[#E0DDD6]" />

      {/* Type + Format */}
      <div className="flex items-center gap-2">
        <select
          value={localFilters.cardType || ''}
          onChange={(e) => updateFilter('cardType', e.target.value || undefined)}
          className="h-9 w-32 border-2 border-[#111111] bg-white px-2 text-sm text-[#111111] outline-none"
        >
          <option value="">Type</option>
          {CARD_TYPES.map((t) => <option key={t} value={t.toLowerCase()}>{t}</option>)}
        </select>
        <select
          value={localFilters.format || ''}
          onChange={(e) => updateFilter('format', e.target.value || undefined)}
          className="h-9 w-32 border-2 border-[#111111] bg-white px-2 text-sm text-[#111111] outline-none"
        >
          <option value="">Format</option>
          {FORMATS.map((f) => <option key={f} value={f.toLowerCase()}>{f}</option>)}
        </select>
      </div>
    </div>
  )
}

// Inline row for desktop filter bar
function FilterInlineRow({
  localFilters,
  updateFilter,
  handleColorClick,
}: {
  localFilters: FilterState
  updateFilter: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void
  handleColorClick: (color: string) => void
}) {
  const sep = <div className="mx-2 h-5 w-px shrink-0 bg-[#E0DDD6]" aria-hidden />
  return (
    <div className="flex w-max min-w-full items-center gap-2">

      {/* Colors */}
      <div className="flex shrink-0 items-center gap-1">
        {COLORS.map((c) => {
          const isSelected = localFilters.colors?.includes(c.value)
          return (
            <button
              key={c.value}
              onClick={() => handleColorClick(c.value)}
              className="flex h-8 w-8 items-center justify-center border-2 text-[10px] font-bold transition-colors"
              style={isSelected
                ? { backgroundColor: c.bg, borderColor: c.border, color: c.textOnSelected }
                : { backgroundColor: c.paleBg, borderColor: c.border, color: c.border }
              }
              title={c.label}
            >
              {c.value}
            </button>
          )
        })}
      </div>

      {/* Match mode */}
      <button
        onClick={() => {
          const modes: ('at_least' | 'at_most' | 'exact')[] = ['at_least', 'at_most', 'exact']
          const current = localFilters.matchMode || 'at_least'
          updateFilter('matchMode', modes[(modes.indexOf(current) + 1) % modes.length])
        }}
        className={cn(
          'flex h-8 w-16 shrink-0 items-center justify-center border-2 text-[10px] font-bold whitespace-nowrap transition-colors',
          localFilters.matchMode && localFilters.matchMode !== 'at_least'
            ? 'border-[#111111] bg-[#111111] text-white'
            : 'border-[#CCCCCC] bg-transparent text-[#111111] hover:border-[#111111]'
        )}
      >
        {localFilters.matchMode === 'exact' ? 'Exact' : localFilters.matchMode === 'at_most' ? 'At Most' : 'At Least'}
      </button>

      {/* Color feature */}
      <button
        onClick={() => {
          const features: ('identity' | 'colors')[] = ['identity', 'colors']
          const current = localFilters.colorFeature || 'identity'
          updateFilter('colorFeature', features[(features.indexOf(current) + 1) % features.length])
        }}
        className={cn(
          'flex h-8 w-[4.25rem] shrink-0 items-center justify-center border-2 text-[10px] font-bold whitespace-nowrap transition-colors',
          localFilters.colorFeature === 'colors'
            ? 'border-[#111111] bg-[#111111] text-white'
            : 'border-[#CCCCCC] bg-transparent text-[#111111] hover:border-[#111111]'
        )}
      >
        {localFilters.colorFeature === 'colors' ? 'Cost' : 'Identity'}
      </button>

      {sep}

      {/* CMC */}
      <div className="flex shrink-0 items-center gap-1">
        <span className="font-display text-[9px] font-bold uppercase leading-none tracking-[0.14em] text-[#7A7670]">CMC</span>
        <div className="flex h-8 items-center border-2 border-[#111111]">
          <input
            type="number"
            placeholder="0"
            min={0} max={20}
            value={localFilters.cmcMin ?? ''}
            onChange={(e) => updateFilter('cmcMin', e.target.value ? Number(e.target.value) : undefined)}
            className="h-full w-8 bg-transparent px-0.5 text-center text-xs text-[#111111] outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
          <div className="h-3 w-px bg-[#E0DDD6]" />
          <input
            type="number"
            placeholder="∞"
            min={0} max={20}
            value={localFilters.cmcMax ?? ''}
            onChange={(e) => updateFilter('cmcMax', e.target.value ? Number(e.target.value) : undefined)}
            className="h-full w-8 bg-transparent px-0.5 text-center text-xs text-[#111111] outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
        </div>
      </div>

      {/* Rarities */}
      <div className="flex shrink-0 items-center gap-1">
        {RARITIES.map((r) => {
          const isSelected = localFilters.rarities?.includes(r.value)
          return (
            <button
              key={r.value}
              onClick={() => {
                const current = localFilters.rarities ?? []
                const next = isSelected
                  ? current.filter((v) => v !== r.value)
                  : [...current, r.value]
                updateFilter('rarities', next.length ? next : undefined)
              }}
              className="flex h-8 w-8 shrink-0 items-center justify-center border-2 text-[10px] font-bold transition-colors"
              style={isSelected
                ? { backgroundColor: r.bg, borderColor: r.border, color: r.textOnSelected }
                : { backgroundColor: r.paleBg, borderColor: r.border, color: r.border }
              }
              title={r.label}
            >
              {r.short}
            </button>
          )
        })}
      </div>

      {sep}

      {/* Type */}
      <select
        value={localFilters.cardType || ''}
        onChange={(e) => updateFilter('cardType', e.target.value || undefined)}
        className="h-8 min-w-[4rem] shrink-0 border-2 border-[#111111] bg-white px-1 text-xs text-[#111111] outline-none"
      >
        <option value="">Type</option>
        {CARD_TYPES.map((t) => <option key={t} value={t.toLowerCase()}>{t}</option>)}
      </select>

      {/* Format */}
      <select
        value={localFilters.format || ''}
        onChange={(e) => updateFilter('format', e.target.value || undefined)}
        className="h-8 min-w-[4.5rem] shrink-0 border-2 border-[#111111] bg-white px-1 text-xs text-[#111111] outline-none"
      >
        <option value="">Format</option>
        {FORMATS.map((f) => <option key={f} value={f.toLowerCase()}>{f}</option>)}
      </select>

    </div>
  )
}

// --- Main Component ---

export function FilterBar({ filters, onFilterChange, variant = 'button' }: FilterBarProps) {
  const [localFilters, setLocalFilters] = useState<FilterState>(filters)
  const [hasChanges, setHasChanges] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)

  useEffect(() => {
    if (!hasChanges) queueMicrotask(() => setLocalFilters(filters))
  }, [filters, hasChanges])

  const draftFilters: FilterState = hasChanges ? localFilters : filters

  const handleApply = () => {
    onFilterChange(localFilters)
    setHasChanges(false)
    setIsModalOpen(false)
  }

  const handleReset = () => {
    const empty: FilterState = {}
    setLocalFilters(empty)
    onFilterChange(empty)
    setHasChanges(false)
    setIsModalOpen(false)
  }

  const updateFilter = <K extends keyof FilterState>(key: K, value: FilterState[K]) => {
    setLocalFilters({ ...draftFilters, [key]: value })
    setHasChanges(true)
  }

  const handleColorClick = (color: string) => {
    const current = draftFilters.colors ? draftFilters.colors.split('') : []
    const isSelected = current.includes(color)
    let next = [...current]
    if (color === 'C') {
      next = isSelected ? [] : ['C']
    } else {
      if (next.includes('C')) next = []
      next = isSelected ? next.filter((c) => c !== color) : [...next, color]
    }
    updateFilter('colors', next.join('') || undefined)
  }

  const activeCount = Object.keys(filters).filter(
    (k) => filters[k as keyof FilterState] !== undefined
  ).length

  const inputProps = { localFilters: draftFilters, updateFilter, handleColorClick }

  if (variant === 'inline') {
    return (
      <div className="flex w-full items-center gap-0">
        <div className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:[display:none]">
          <FilterInlineRow {...inputProps} />
        </div>
        <div className="mx-2 h-7 w-px shrink-0 bg-[#E0DDD6]" aria-hidden />
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            onClick={handleReset}
            className="flex h-8 items-center gap-1 border-2 border-[#CCCCCC] bg-transparent px-2.5 font-display text-[10px] font-bold uppercase tracking-wide text-[#7A7670] transition-colors hover:border-[#111111] hover:text-[#111111]"
          >
            <ArrowCounterClockwise className="h-3 w-3" />
            Reset
          </button>
          <button
            onClick={handleApply}
            disabled={!hasChanges}
            className={cn(
              'flex h-8 items-center gap-1.5 border-2 px-3 font-display text-[10px] font-bold uppercase tracking-wide transition-colors',
              hasChanges
                ? 'border-[#111111] bg-[#111111] text-white hover:bg-[#333]'
                : 'cursor-not-allowed border-[#CCCCCC] bg-transparent text-[#CCCCCC]'
            )}
          >
            Apply
          </button>
        </div>
      </div>
    )
  }

  return (
    <>
      <button
        onClick={() => {
          setLocalFilters(filters)
          setHasChanges(false)
          setIsModalOpen(true)
        }}
        className={cn(
          'flex cursor-pointer items-center gap-2 border-2 px-4 py-2 font-display text-[11px] font-bold uppercase tracking-[0.12em] transition-colors',
          activeCount > 0
            ? 'border-[#111111] bg-[#111111] text-white'
            : 'border-[#111111] bg-transparent text-[#111111] hover:bg-[#111111] hover:text-white'
        )}
      >
        <Funnel className="h-3.5 w-3.5" weight={activeCount > 0 ? 'fill' : 'regular'} />
        Filters
        {activeCount > 0 && (
          <span className="flex h-4 w-4 items-center justify-center bg-white font-display text-[9px] font-bold text-[#111111]">
            {activeCount}
          </span>
        )}
      </button>

      {isModalOpen
        ? createPortal(
            <div className="fixed inset-0 z-[9999] overflow-y-auto bg-black/50">
              <div className="flex min-h-full items-start justify-center p-4 sm:items-center">
                <div className="max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto border-2 border-[#111111] bg-white p-6">
                  <div className="mb-6 flex items-center justify-between">
                    <h3 className="font-display text-lg font-[800] uppercase tracking-wide text-[#111111]">
                      Filters
                    </h3>
                    <button
                      onClick={() => { setLocalFilters(filters); setHasChanges(false); setIsModalOpen(false) }}
                      className="flex h-8 w-8 items-center justify-center border-2 border-[#111111] text-[#111111] transition-colors hover:bg-[#111111] hover:text-white"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>

                  <div className="mb-8">
                    <FilterInputs {...inputProps} isMobile={true} />
                  </div>

                  <div className="flex items-center gap-3 border-t-2 border-[#111111] pt-5">
                    <button
                      onClick={handleReset}
                      className="flex flex-1 items-center justify-center gap-2 border-2 border-[#111111] py-2.5 font-display text-[11px] font-bold uppercase tracking-wide text-[#111111] transition-colors hover:bg-[#111111] hover:text-white"
                    >
                      <ArrowCounterClockwise className="h-3.5 w-3.5" />
                      Reset
                    </button>
                    <button
                      onClick={handleApply}
                      disabled={!hasChanges}
                      className={cn(
                        'flex flex-1 items-center justify-center gap-2 border-2 py-2.5 font-display text-[11px] font-bold uppercase tracking-wide transition-colors',
                        hasChanges
                          ? 'border-[#111111] bg-[#111111] text-white hover:bg-[#333]'
                          : 'cursor-not-allowed border-[#CCCCCC] bg-transparent text-[#CCCCCC]'
                      )}
                    >
                      <Funnel weight="fill" className="h-3.5 w-3.5" />
                      Apply
                    </button>
                  </div>
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  )
}
