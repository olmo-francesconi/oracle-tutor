import { Funnel, ArrowCounterClockwise, X } from '@phosphor-icons/react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../lib/cn'
import type { FilterState } from '../types'

interface FilterBarProps {
  filters: FilterState
  onFilterChange: (filters: FilterState) => void
}

const COLORS = [
  { value: 'W', label: 'White', color: 'bg-yellow-100', text: 'text-yellow-900', glow: 'shadow-[0_0_10px_rgba(253,224,71,0.6)]' },
  { value: 'U', label: 'Blue', color: 'bg-blue-100', text: 'text-blue-900', glow: 'shadow-[0_0_10px_rgba(147,197,253,0.6)]' },
  { value: 'B', label: 'Black', color: 'bg-gray-400', text: 'text-gray-900', glow: 'shadow-[0_0_10px_rgba(156,163,175,0.6)]' },
  { value: 'R', label: 'Red', color: 'bg-red-100', text: 'text-red-900', glow: 'shadow-[0_0_10px_rgba(252,165,165,0.6)]' },
  { value: 'G', label: 'Green', color: 'bg-green-100', text: 'text-green-900', glow: 'shadow-[0_0_10px_rgba(134,239,172,0.6)]' },
  { value: 'C', label: 'Colorless', color: 'bg-slate-200', text: 'text-slate-600', glow: 'shadow-[0_0_10px_rgba(203,213,225,0.6)]' },
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

const RARITIES = ['Common', 'Uncommon', 'Rare', 'Mythic']

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
  isExclusive: boolean
  updateFilter: (key: keyof FilterState, value: any) => void
  toggleExclusive: () => void
  handleColorClick: (color: string) => void
  isMobile?: boolean
}

function FilterInputs({
  localFilters,
  isExclusive,
  updateFilter,
  toggleExclusive,
  handleColorClick,
  isMobile = false,
}: FilterInputsProps) {
  return (
    <div className={cn("flex items-center gap-6", isMobile && "flex-col items-stretch gap-6")}>
      {/* Colors */}
      <div className={cn("flex items-center gap-2", isMobile && "justify-between")}>
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
        
        {/* Exclusive Toggle */}
        <button
          onClick={toggleExclusive}
          className={cn(
            'ml-1 flex h-8 items-center gap-2 rounded-lg border border-white/5 bg-[#333] px-3 text-xs font-bold transition-all hover:bg-[#404040]',
            isExclusive
              ? 'text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.2)]'
              : 'text-[#737373]'
          )}
          title="Match Exact Colors Only"
        >
          <div
            className={cn(
              'h-2 w-2 rounded-full transition-colors',
              isExclusive
                ? 'bg-emerald-400 shadow-[0_0_5px_currentColor]'
                : 'bg-[#525252]'
            )}
          />
          Exact
        </button>
      </div>

      {/* Selects Group */}
      <div className={cn("flex items-center gap-3", isMobile && "flex-col items-stretch")}>
        <select
          value={localFilters.cardType || ''}
          onChange={(e) =>
            updateFilter('cardType', e.target.value || undefined)
          }
          className="h-10 rounded-lg border border-white/10 bg-[#333] px-3 text-sm font-medium text-[#f5f2eb] outline-none transition-colors hover:bg-[#404040] focus:border-[#e3dccb]/50"
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
          className="h-10 rounded-lg border border-white/10 bg-[#333] px-3 text-sm font-medium text-[#f5f2eb] outline-none transition-colors hover:bg-[#404040] focus:border-[#e3dccb]/50"
        >
          <option value="">Format</option>
          {FORMATS.map((f) => (
            <option key={f} value={f.toLowerCase()}>
              {f}
            </option>
          ))}
        </select>

        <select
          value={localFilters.rarity || ''}
          onChange={(e) => updateFilter('rarity', e.target.value || undefined)}
          className="h-10 rounded-lg border border-white/10 bg-[#333] px-3 text-sm font-medium text-[#f5f2eb] outline-none transition-colors hover:bg-[#404040] focus:border-[#e3dccb]/50"
        >
          <option value="">Rarity</option>
          {RARITIES.map((r) => (
            <option key={r} value={r.toLowerCase()}>
              {r}
            </option>
          ))}
        </select>
      </div>

      {/* CMC */}
      <div className={cn("flex items-center gap-2", isMobile && "justify-between")}>
        <span className="text-xs font-bold uppercase tracking-wider text-[#737373]">
          CMC
        </span>
        <div className={cn("flex items-center rounded-lg border border-white/10 bg-[#333]", isMobile && "flex-1 ml-4")}>
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
            className="h-10 w-12 flex-1 rounded-l-lg bg-transparent px-2 text-center text-sm font-medium text-[#f5f2eb] outline-none transition-colors hover:bg-[#404040] focus:bg-[#404040] focus:placeholder-transparent [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
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
            className="h-10 w-12 flex-1 rounded-r-lg bg-transparent px-2 text-center text-sm font-medium text-[#f5f2eb] outline-none transition-colors hover:bg-[#404040] focus:bg-[#404040] focus:placeholder-transparent [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
        </div>
      </div>
    </div>
  )
}

// --- Main Component ---

export function FilterBar({ filters, onFilterChange }: FilterBarProps) {
  const [localFilters, setLocalFilters] = useState<FilterState>(filters)
  const [hasChanges, setHasChanges] = useState(false)
  const [isExclusive, setIsExclusive] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [showInline, setShowInline] = useState(true)
  const [isMounted, setIsMounted] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)
  const measureBarRef = useRef<HTMLDivElement>(null)

  // Sync local state when props change externally
  useEffect(() => {
    setLocalFilters(filters)
    setHasChanges(false)
    setIsExclusive(filters.matchMode === 'exact')
  }, [filters])

  useEffect(() => {
    setIsMounted(true)
  }, [])

  const handleApply = () => {
    onFilterChange(localFilters)
    setHasChanges(false)
    setIsModalOpen(false)
  }

  const handleReset = () => {
    const emptyFilters: FilterState = {}
    setLocalFilters(emptyFilters)
    setIsExclusive(false)
    onFilterChange(emptyFilters)
    setHasChanges(false)
    setIsModalOpen(false)
  }

  const updateFilter = <K extends keyof FilterState>(
    key: K,
    value: FilterState[K]
  ) => {
    setLocalFilters((prev) => {
      const next = { ...prev, [key]: value }
      setHasChanges(true)
      return next
    })
  }

  const toggleExclusive = () => {
    const newExclusive = !isExclusive
    setIsExclusive(newExclusive)
    updateFilter('matchMode', newExclusive ? 'exact' : 'subset')
  }

  const handleColorClick = (color: string) => {
    const currentColors = localFilters.colors ? localFilters.colors.split('') : []
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
  const inputProps = useMemo(
    () => ({
      localFilters,
      isExclusive,
      updateFilter,
      toggleExclusive,
      handleColorClick,
    }),
    [localFilters, isExclusive]
  )

  const recomputeLayout = () => {
    const containerW = containerRef.current?.clientWidth ?? 0
    const neededW = measureBarRef.current?.scrollWidth ?? 0
    if (containerW <= 0 || neededW <= 0) return

    // Small hysteresis to avoid flicker when near the threshold.
    const hysteresisPx = 24
    setShowInline((prev) => {
      if (prev) return containerW >= (neededW - hysteresisPx)
      return containerW >= (neededW + hysteresisPx)
    })
  }

  useLayoutEffect(() => {
    recomputeLayout()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    recomputeLayout()

    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => recomputeLayout())
    ro.observe(el)
    return () => ro.disconnect()
    // Recompute when controls that affect width change.
  }, [hasChanges, isExclusive, localFilters.colors, localFilters.cardType, localFilters.format, localFilters.rarity])

  return (
    <>
      <div ref={containerRef} className="w-full">
        {/* Hidden measurement bar (offscreen). Used to decide when to switch layouts dynamically. */}
        <div className="pointer-events-none fixed -left-[9999px] top-0 opacity-0">
          <div
            ref={measureBarRef}
            className="flex w-max items-center justify-between gap-4 rounded-xl border border-white/5 bg-[#262626] px-6 py-3 shadow-sm"
          >
            <div className="flex items-center">
              <FilterInputs {...inputProps} />
            </div>
            <div className="flex flex-shrink-0 items-center gap-3 border-l border-white/10 pl-6">
              <button className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/5 bg-[#333] text-[#737373]">
                <ArrowCounterClockwise className="h-5 w-5" />
              </button>
              <button className="flex h-10 items-center gap-2 rounded-lg bg-[#e3dccb] px-6 text-sm font-bold text-[#1c1c1c]">
                <Funnel weight="fill" className="h-4 w-4" />
                Apply
              </button>
            </div>
          </div>
        </div>

        {/* Inline bar when it fits */}
        {showInline ? (
          <div className="flex w-full items-center justify-between gap-4 rounded-xl border border-white/5 bg-[#262626] px-6 py-3 shadow-sm">
            <div className="flex flex-1 items-center">
              <FilterInputs {...inputProps} />
            </div>

            <div className="flex flex-shrink-0 items-center gap-3 border-l border-white/10 pl-6">
              <button
                onClick={handleReset}
                className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/5 bg-[#333] text-[#737373] transition-all hover:bg-[#404040] hover:text-[#f5f2eb]"
                title="Reset Filters"
              >
                <ArrowCounterClockwise className="h-5 w-5" />
              </button>
              <button
                onClick={handleApply}
                disabled={!hasChanges}
                className={cn(
                  'flex h-10 items-center gap-2 rounded-lg px-6 text-sm font-bold transition-all',
                  hasChanges
                    ? 'cursor-pointer bg-[#e3dccb] text-[#1c1c1c] shadow-lg hover:bg-white active:scale-95'
                    : 'cursor-not-allowed bg-[#333] text-[#737373] opacity-50'
                )}
              >
                <Funnel weight="fill" className="h-4 w-4" />
                Apply
              </button>
            </div>
          </div>
        ) : (
          <div className="flex w-full justify-end">
            <button
              onClick={() => setIsModalOpen(true)}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-lg border border-white/5 bg-[#262626] px-4 py-2 text-sm font-medium text-[#f5f2eb] shadow-sm transition-all hover:border-[#e3dccb]/30 hover:bg-[#333] active:scale-95',
                activeCount > 0 && 'border-[#e3dccb]/30 bg-[#333]'
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
          </div>
        )}
      </div>

      {/* Mobile Filter Modal (Portal to body so it overlays the entire card grid) */}
      {isMounted && isModalOpen
        ? createPortal(
            <div className="fixed inset-0 z-[9999] overflow-y-auto bg-black/60 backdrop-blur-sm">
              <div className="flex min-h-full items-start justify-center p-4 sm:items-center">
                <div className="w-full max-w-md max-h-[calc(100vh-2rem)] overflow-y-auto rounded-2xl border border-white/10 bg-[#1c1c1c] p-6 shadow-2xl">
                  <div className="mb-6 flex items-center justify-between">
                    <h3 className="text-lg font-bold text-[#f5f2eb]">Filters</h3>
                    <button
                      onClick={() => setIsModalOpen(false)}
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
