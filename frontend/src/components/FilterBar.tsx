import { Funnel, ArrowCounterClockwise, X } from '@phosphor-icons/react'
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../lib/cn'
import type { FilterState } from '../types'

interface FilterBarProps {
  filters: FilterState
  onFilterChange: (filters: FilterState) => void
}

const COLORS = [
  {
    value: 'W',
    label: 'White',
    color: 'bg-[#f0f0e0]',
    text: 'text-[#4a4a4a]',
    glow: 'shadow-[0_0_10px_rgba(240,240,224,0.4)]',
  },
  {
    value: 'U',
    label: 'Blue',
    color: 'bg-[#c1d7e8]',
    text: 'text-[#1e3a8a]',
    glow: 'shadow-[0_0_10px_rgba(193,215,232,0.4)]',
  },
  {
    value: 'B',
    label: 'Black',
    color: 'bg-[#bab1ab]',
    text: 'text-[#1c1c1c]',
    glow: 'shadow-[0_0_10px_rgba(186,177,171,0.4)]',
  },
  {
    value: 'R',
    label: 'Red',
    color: 'bg-[#e8c1c1]',
    text: 'text-[#7f1d1d]',
    glow: 'shadow-[0_0_10px_rgba(232,193,193,0.4)]',
  },
  {
    value: 'G',
    label: 'Green',
    color: 'bg-[#c6e0c8]',
    text: 'text-[#14532d]',
    glow: 'shadow-[0_0_10px_rgba(198,224,200,0.4)]',
  },
  {
    value: 'C',
    label: 'Colorless',
    color: 'bg-[#dcdcdc]',
    text: 'text-[#475569]',
    glow: 'shadow-[0_0_10px_rgba(220,220,220,0.4)]',
  },
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

// --- Sub-components for reuse ---

interface FilterInputsProps {
  localFilters: FilterState
  updateFilter: <K extends keyof FilterState>(
    key: K,
    value: FilterState[K]
  ) => void
  handleColorClick: (color: string) => void
  isMobile?: boolean
}

function FilterInputs({
  localFilters,
  updateFilter,
  handleColorClick,
  isMobile = false,
}: FilterInputsProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center gap-4',
        isMobile && 'w-full gap-6'
      )}
    >
      {/* Row 1: Colors */}
      <div className="flex items-center gap-2">
        {COLORS.map((c) => {
          const isSelected = localFilters.colors?.includes(c.value)
          return (
            <button
              key={c.value}
              onClick={() => handleColorClick(c.value)}
              className={cn(
                'flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition-all duration-300',
                isSelected
                  ? `${c.color} ${c.text} scale-110 shadow-sm ring-1 ring-white/20`
                  : 'bg-[#333] text-[#737373] hover:bg-[#404040]'
              )}
              title={c.label}
            >
              {c.value}
            </button>
          )
        })}
      </div>

      {/* Row 2: Mode Buttons */}
      <div className="flex items-center gap-2">
        {/* Match Mode Selector */}
        <button
          onClick={() => {
            const modes: ('at_least' | 'at_most' | 'exact')[] = [
              'at_least',
              'at_most',
              'exact',
            ]
            const current = localFilters.matchMode || 'at_least'
            const next = modes[(modes.indexOf(current) + 1) % modes.length]
            updateFilter('matchMode', next)
          }}
          className={cn(
            'flex h-8 w-32 shrink-0 items-center justify-center rounded-lg border border-white/5 bg-[#333] px-3 text-xs font-bold whitespace-nowrap transition-all hover:bg-[#404040] hover:text-[#f5f2eb]',
            localFilters.matchMode && localFilters.matchMode !== 'at_least'
              ? 'border-[#e3dccb]/30 text-[#e3dccb]'
              : 'text-[#737373]'
          )}
          title="Color Match Mode"
        >
          {localFilters.matchMode === 'exact'
            ? 'Exact'
            : localFilters.matchMode === 'at_most'
              ? 'At Most'
              : 'At Least'}
        </button>

        {/* Color Feature Selector */}
        <button
          onClick={() => {
            const features: ('identity' | 'colors')[] = ['identity', 'colors']
            const current = localFilters.colorFeature || 'identity'
            const next =
              features[(features.indexOf(current) + 1) % features.length]
            updateFilter('colorFeature', next)
          }}
          className={cn(
            'flex h-8 w-32 shrink-0 items-center justify-center rounded-lg border border-white/5 bg-[#333] px-3 text-xs font-bold whitespace-nowrap transition-all hover:bg-[#404040] hover:text-[#f5f2eb]',
            localFilters.colorFeature === 'colors'
              ? 'border-[#e3dccb]/30 text-[#e3dccb]'
              : 'text-[#737373]'
          )}
          title="Filter by Color Identity or Mana Cost"
        >
          {localFilters.colorFeature === 'colors' ? 'Cost' : 'Identity'}
        </button>
      </div>

      {/* Spacer */}
      <div className="h-px w-full bg-gradient-to-r from-transparent via-white/10 to-transparent" />

      {/* Row 3: CMC and Rarity */}
      <div className="flex items-center gap-4">
        {/* CMC */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider text-[#737373] uppercase">
            CMC
          </span>
          <div className="flex items-center rounded-lg border border-white/10 bg-[#333]">
            <input
              type="number"
              placeholder="0"
              min="0"
              max="20"
              value={localFilters.cmcMin ?? ''}
              onChange={(e) =>
                updateFilter(
                  'cmcMin',
                  e.target.value ? Number(e.target.value) : undefined
                )
              }
              className="h-10 w-12 flex-1 [appearance:textfield] rounded-l-lg bg-transparent px-2 text-center text-base font-medium text-[#f5f2eb] transition-colors outline-none hover:bg-[#404040] focus:bg-[#404040] focus:placeholder-transparent md:text-sm [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            <div className="h-4 w-px bg-white/10" />
            <input
              type="number"
              placeholder="∞"
              min="0"
              max="20"
              value={localFilters.cmcMax ?? ''}
              onChange={(e) =>
                updateFilter(
                  'cmcMax',
                  e.target.value ? Number(e.target.value) : undefined
                )
              }
              className="h-10 w-12 flex-1 [appearance:textfield] rounded-r-lg bg-transparent px-2 text-center text-base font-medium text-[#f5f2eb] transition-colors outline-none hover:bg-[#404040] focus:bg-[#404040] focus:placeholder-transparent md:text-sm [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
          </div>
        </div>

        {/* Rarity Circle */}
        <button
          onClick={() => {
            const rarities = ['common', 'uncommon', 'rare', 'mythic']
            const current = localFilters.rarity
            let next: string | undefined

            if (!current) {
              next = 'common'
            } else {
              const idx = rarities.indexOf(current)
              if (idx === rarities.length - 1) {
                next = undefined
              } else {
                next = rarities[idx + 1]
              }
            }
            updateFilter('rarity', next)
          }}
          className={cn(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white/10 text-xs font-bold transition-all',
            !localFilters.rarity &&
              'bg-[#333] text-[#737373] hover:bg-[#404040]',
            localFilters.rarity === 'common' &&
              'border-zinc-500/30 bg-zinc-500/20 text-zinc-400',
            localFilters.rarity === 'uncommon' &&
              'border-blue-500/30 bg-blue-500/20 text-blue-300',
            localFilters.rarity === 'rare' &&
              'border-amber-500/30 bg-amber-500/20 text-amber-300',
            localFilters.rarity === 'mythic' &&
              'border-orange-600/30 bg-orange-600/20 text-orange-400'
          )}
          title="Rarity"
        >
          {localFilters.rarity ? localFilters.rarity[0].toUpperCase() : 'R'}
        </button>
      </div>

      {/* Spacer */}
      <div className="h-px w-full bg-gradient-to-r from-transparent via-white/10 to-transparent" />

      {/* Row 4: Type and Format */}
      <div className="flex items-center gap-2">
        <select
          value={localFilters.cardType || ''}
          onChange={(e) =>
            updateFilter('cardType', e.target.value || undefined)
          }
          className="h-10 w-32 rounded-lg border border-white/10 bg-[#333] px-3 text-sm font-medium text-[#f5f2eb] transition-colors outline-none hover:bg-[#404040] focus:border-[#e3dccb]/50"
        >
          <option value="">Type</option>
          {CARD_TYPES.map((t) => (
            <option key={t} value={t.toLowerCase()}>
              {t}
            </option>
          ))}
        </select>

        <select
          value={localFilters.format || ''}
          onChange={(e) => updateFilter('format', e.target.value || undefined)}
          className="h-10 w-32 rounded-lg border border-white/10 bg-[#333] px-3 text-sm font-medium text-[#f5f2eb] transition-colors outline-none hover:bg-[#404040] focus:border-[#e3dccb]/50"
        >
          <option value="">Format</option>
          {FORMATS.map((f) => (
            <option key={f} value={f.toLowerCase()}>
              {f}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

// --- Main Component ---

export function FilterBar({ filters, onFilterChange }: FilterBarProps) {
  const [localFilters, setLocalFilters] = useState<FilterState>(filters)
  const [hasChanges, setHasChanges] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)

  // If the user hasn't modified the draft, always reflect the latest committed filters.
  const draftFilters: FilterState = hasChanges ? localFilters : filters

  const handleApply = () => {
    onFilterChange(localFilters)
    setHasChanges(false)
    setIsModalOpen(false)
  }

  const handleReset = () => {
    const emptyFilters: FilterState = {}
    setLocalFilters(emptyFilters)
    onFilterChange(emptyFilters)
    setHasChanges(false)
    setIsModalOpen(false)
  }

  const updateFilter = <K extends keyof FilterState>(
    key: K,
    value: FilterState[K]
  ) => {
    // Always base updates on the currently rendered draft state, not potentially stale local state.
    setLocalFilters({ ...draftFilters, [key]: value })
    setHasChanges(true)
  }

  const handleColorClick = (color: string) => {
    const currentColors = draftFilters.colors
      ? draftFilters.colors.split('')
      : []
    const isSelected = currentColors.includes(color)

    let newColors = [...currentColors]

    if (color === 'C') {
      if (isSelected) {
        newColors = []
      } else {
        newColors = ['C']
      }
    } else {
      if (newColors.includes('C')) {
        newColors = []
      }

      if (isSelected) {
        newColors = newColors.filter((c) => c !== color)
      } else {
        newColors.push(color)
      }
    }

    updateFilter('colors', newColors.join('') || undefined)
  }

  const activeCount = Object.keys(filters).filter(
    (k) => filters[k as keyof FilterState] !== undefined
  ).length

  // Shared props for inputs
  const inputProps = {
    localFilters: draftFilters,
    updateFilter,
    handleColorClick,
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
          'flex cursor-pointer items-center gap-2 rounded-full border border-white/10 bg-[#1c1c1c]/80 px-4 py-2 text-sm font-medium text-[#f5f2eb] shadow-lg backdrop-blur-md transition-all hover:border-[#e3dccb]/30 hover:bg-[#262626] active:scale-95',
          activeCount > 0 && 'border-[#e3dccb]/30 bg-[#262626]'
        )}
      >
        <Funnel
          className={cn('h-4 w-4', activeCount > 0 && 'text-[#e3dccb]')}
          weight={activeCount > 0 ? 'fill' : 'regular'}
        />
        <span>Filters</span>
        {activeCount > 0 && (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#e3dccb] text-xs font-bold text-[#1c1c1c]">
            {activeCount}
          </span>
        )}
      </button>

      {/* Mobile Filter Modal (Portal to body so it overlays the entire card grid) */}
      {isModalOpen
        ? createPortal(
            <div className="fixed inset-0 z-[9999] overflow-y-auto bg-black/60 backdrop-blur-sm">
              <div className="flex min-h-full items-start justify-center p-4 sm:items-center">
                <div className="max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto rounded-2xl border border-white/10 bg-[#1c1c1c] p-6 shadow-2xl">
                  <div className="mb-6 flex items-center justify-between">
                    <h3 className="text-lg font-bold text-[#f5f2eb]">
                      Filters
                    </h3>
                    <button
                      onClick={() => {
                        setLocalFilters(filters)
                        setHasChanges(false)
                        setIsModalOpen(false)
                      }}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-[#737373] transition-colors hover:bg-[#333] hover:text-[#f5f2eb]"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>

                  <div className="mb-8">
                    <FilterInputs {...inputProps} isMobile={true} />
                  </div>

                  <div className="flex items-center gap-3 border-t border-white/10 pt-6">
                    <button
                      onClick={handleReset}
                      className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-white/5 bg-[#333] py-2.5 text-sm font-medium text-[#737373] transition-all hover:bg-[#404040] hover:text-[#f5f2eb]"
                    >
                      <ArrowCounterClockwise className="h-4 w-4" />
                      Reset
                    </button>
                    <button
                      onClick={handleApply}
                      disabled={!hasChanges}
                      className={cn(
                        'flex flex-1 items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-bold transition-all',
                        hasChanges
                          ? 'cursor-pointer bg-[#e3dccb] text-[#1c1c1c] shadow-lg hover:bg-white active:scale-95'
                          : 'cursor-not-allowed bg-[#333] text-[#737373] opacity-50'
                      )}
                    >
                      <Funnel weight="fill" className="h-4 w-4" />
                      Apply Filters
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
