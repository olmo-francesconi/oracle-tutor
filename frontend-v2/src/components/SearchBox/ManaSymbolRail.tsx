import { useEffect, useState, useRef } from 'react'
import { getManaClass } from '../../lib/manaSymbols'

const SYMBOL_SCROLL_STEP = 180

const GENERIC_MANA_SYMBOLS = Array.from({ length: 21 }, (_, index) => `{${index}}`)
const LETTER_SYMBOLS = ['{X}', '{Y}', '{Z}'] as const
const HYBRID_MANA_SYMBOLS = [
  '{W/U}', '{U/B}', '{B/R}', '{R/G}', '{G/W}',
  '{W/B}', '{B/G}', '{G/U}', '{U/R}', '{R/W}',
] as const
const TWO_BRID_MANA_SYMBOLS = ['{2/W}', '{2/U}', '{2/B}', '{2/R}', '{2/G}'] as const
const PHYREXIAN_MANA_SYMBOLS = [
  '{P}', '{W/P}', '{U/P}', '{B/P}', '{R/P}', '{G/P}',
  '{W/U/P}', '{U/B/P}', '{B/R/P}', '{R/G/P}', '{G/W/P}',
] as const
const UTILITY_SYMBOLS = ['{E}', '{TK}', '{A}', '{PAW}'] as const
const SYMBOLS = [
  '{T}', '{Q}', '.',
  '{W}', '{U}', '{B}', '{R}', '{G}', '{C}', '{S}', '.',
  ...UTILITY_SYMBOLS, '.',
  ...HYBRID_MANA_SYMBOLS, '.',
  ...PHYREXIAN_MANA_SYMBOLS, '.',
  ...TWO_BRID_MANA_SYMBOLS, ...GENERIC_MANA_SYMBOLS, ...LETTER_SYMBOLS,
] as const

interface ManaSymbolRailProps {
  onInsert: (symbol: string) => void
  transparentBackground?: boolean
}

export function ManaSymbolRail({
  onInsert,
  transparentBackground = false,
}: ManaSymbolRailProps) {
  const railRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)
  const dragStateRef = useRef<{
    startX: number
    startScrollLeft: number
    moved: boolean
  } | null>(null)
  const isDraggingRef = useRef(false)
  const suppressClickRef = useRef(false)

  useEffect(() => {
    const rail = railRef.current
    if (!rail) return

    const updateScrollState = () => {
      const maxScrollLeft = rail.scrollWidth - rail.clientWidth
      setCanScrollLeft(rail.scrollLeft > 2)
      setCanScrollRight(maxScrollLeft - rail.scrollLeft > 2)
    }

    const handleMouseDown = (event: MouseEvent) => {
      if (!rail || event.button !== 0) return

      dragStateRef.current = {
        startX: event.clientX,
        startScrollLeft: rail.scrollLeft,
        moved: false,
      }

      event.preventDefault()
    }

    const handleMouseMove = (event: MouseEvent) => {
      const dragState = dragStateRef.current
      if (!rail || !dragState) return

      const deltaX = event.clientX - dragState.startX
      if (Math.abs(deltaX) > 4) {
        dragState.moved = true
        isDraggingRef.current = true
      }

      if (!dragState.moved) return

      rail.scrollLeft = dragState.startScrollLeft - deltaX
      event.preventDefault()
    }

    const handleTouchStart = (event: TouchEvent) => {
      if (!rail || event.touches.length !== 1) return

      dragStateRef.current = {
        startX: event.touches[0].clientX,
        startScrollLeft: rail.scrollLeft,
        moved: false,
      }
    }

    const handleTouchMove = (event: TouchEvent) => {
      const dragState = dragStateRef.current
      if (!rail || !dragState || event.touches.length !== 1) return

      const deltaX = event.touches[0].clientX - dragState.startX
      if (Math.abs(deltaX) > 4) {
        dragState.moved = true
        isDraggingRef.current = true
      }

      if (!dragState.moved) return

      rail.scrollLeft = dragState.startScrollLeft - deltaX
      event.preventDefault()
    }

    const clearDragState = () => {
      isDraggingRef.current = false
      dragStateRef.current = null
    }

    const handleDragEnd = () => {
      const dragState = dragStateRef.current
      if (!dragState) return

      suppressClickRef.current = dragState.moved
      window.setTimeout(() => {
        suppressClickRef.current = false
      }, 0)

      clearDragState()
    }

    updateScrollState()

    rail.addEventListener('scroll', updateScrollState, { passive: true })
    rail.addEventListener('mousedown', handleMouseDown)
    rail.addEventListener('touchstart', handleTouchStart, { passive: true })
    window.addEventListener('mousemove', handleMouseMove, { passive: false })
    window.addEventListener('mouseup', handleDragEnd)
    window.addEventListener('touchmove', handleTouchMove, { passive: false })
    window.addEventListener('touchend', handleDragEnd)
    window.addEventListener('touchcancel', handleDragEnd)
    window.addEventListener('resize', updateScrollState)

    return () => {
      rail.removeEventListener('scroll', updateScrollState)
      rail.removeEventListener('mousedown', handleMouseDown)
      rail.removeEventListener('touchstart', handleTouchStart)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleDragEnd)
      window.removeEventListener('touchmove', handleTouchMove)
      window.removeEventListener('touchend', handleDragEnd)
      window.removeEventListener('touchcancel', handleDragEnd)
      window.removeEventListener('resize', updateScrollState)
    }
  }, [])

  const scrollRail = (direction: 'left' | 'right') => {
    const rail = railRef.current
    if (!rail) return

    rail.scrollBy({
      left: direction === 'left' ? -SYMBOL_SCROLL_STEP : SYMBOL_SCROLL_STEP,
      behavior: 'smooth',
    })
  }

  return (
    <div
      className={`relative h-10 w-full min-w-0 ${transparentBackground ? 'bg-transparent' : 'bg-ot-bg'}`}
      aria-label="Mana symbols"
    >
      <div
        ref={railRef}
        className="scrollbar-none flex h-full w-full touch-pan-y select-none items-center gap-1.5 overflow-x-auto overflow-y-hidden whitespace-nowrap px-[10px] py-0"
        role="toolbar"
        aria-label="Insert mana symbols"
      >
        {SYMBOLS.map((symbol, index) => {
          if (symbol === '.') {
            return (
              <span
                key={`divider-${index}`}
                className="flex-none text-[10px] leading-5 text-[color:color-mix(in_srgb,var(--color-ot-ink)_25%,transparent)] opacity-30"
                aria-hidden="true"
              >
                •
              </span>
            )
          }

          const manaClass = getManaClass(symbol)

          return (
            <button
              key={symbol}
              type="button"
              className="inline-flex min-h-9 min-w-9 flex-none cursor-pointer items-center justify-center border-0 bg-transparent p-0 text-ot-ink opacity-30 transition-[background-color,opacity,color,transform] duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:opacity-100 focus-visible:opacity-100 active:opacity-100 motion-reduce:transition-none"
              data-symbol={symbol}
              aria-label={`Insert ${symbol}`}
              title={symbol}
              onClick={(event) => {
                if (suppressClickRef.current) {
                  event.preventDefault()
                  return
                }

                onInsert(symbol)
              }}
            >
              {manaClass ? (
                <i className={`${manaClass} ms-cost text-[0.8rem] leading-none`} aria-hidden="true" />
              ) : (
                symbol
              )}
            </button>
          )
        })}
      </div>

      <div
        className={[
          'pointer-events-none absolute inset-y-0 left-0 w-12 transition-opacity duration-150',
          canScrollLeft ? 'opacity-100' : 'opacity-0',
          transparentBackground
            ? 'bg-[linear-gradient(to_right,rgba(240,237,230,0)_0%,rgba(240,237,230,0)_100%)]'
            : 'bg-[linear-gradient(to_right,var(--color-ot-bg)_0%,rgba(240,237,230,0.92)_38%,rgba(240,237,230,0)_100%)]',
        ].join(' ')}
        aria-hidden="true"
      />
      <div
        className={[
          'pointer-events-none absolute inset-y-0 right-0 w-12 transition-opacity duration-150',
          canScrollRight ? 'opacity-100' : 'opacity-0',
          transparentBackground
            ? 'bg-[linear-gradient(to_left,rgba(240,237,230,0)_0%,rgba(240,237,230,0)_100%)]'
            : 'bg-[linear-gradient(to_left,var(--color-ot-bg)_0%,rgba(240,237,230,0.92)_38%,rgba(240,237,230,0)_100%)]',
        ].join(' ')}
        aria-hidden="true"
      />

      {canScrollLeft ? (
        <button
          type="button"
          className="absolute left-1 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center border-0 bg-transparent p-0 text-xs text-ot-ink/75 transition-colors duration-150 hover:text-ot-ink"
          onClick={() => scrollRail('left')}
          aria-label="Scroll symbols left"
        >
          <span className="text-base leading-none" aria-hidden="true">‹</span>
        </button>
      ) : null}

      {canScrollRight ? (
        <button
          type="button"
          className="absolute right-1 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center border-0 bg-transparent p-0 text-xs text-ot-ink/75 transition-colors duration-150 hover:text-ot-ink"
          onClick={() => scrollRail('right')}
          aria-label="Scroll symbols right"
        >
          <span className="text-base leading-none" aria-hidden="true">›</span>
        </button>
      ) : null}
    </div>
  )
}
