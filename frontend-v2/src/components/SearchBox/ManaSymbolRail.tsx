import { useEffect, useRef } from 'react'
import { getManaClass } from '../../lib/manaSymbols'

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
}

export function ManaSymbolRail({ onInsert }: ManaSymbolRailProps) {
  const railRef = useRef<HTMLDivElement>(null)
  const dragStateRef = useRef<{
    startX: number
    startScrollLeft: number
    moved: boolean
  } | null>(null)
  const suppressClickRef = useRef(false)

  useEffect(() => {
    const rail = railRef.current

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
        rail.dataset.dragging = 'true'
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
        rail.dataset.dragging = 'true'
      }

      if (!dragState.moved) return

      rail.scrollLeft = dragState.startScrollLeft - deltaX
      event.preventDefault()
    }

    const clearDragState = () => {
      const rail = railRef.current
      if (rail) {
        delete rail.dataset.dragging
      }
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

    rail?.addEventListener('mousedown', handleMouseDown)
    rail?.addEventListener('touchstart', handleTouchStart, { passive: true })
    window.addEventListener('mousemove', handleMouseMove, { passive: false })
    window.addEventListener('mouseup', handleDragEnd)
    window.addEventListener('touchmove', handleTouchMove, { passive: false })
    window.addEventListener('touchend', handleDragEnd)
    window.addEventListener('touchcancel', handleDragEnd)

    return () => {
      rail?.removeEventListener('mousedown', handleMouseDown)
      rail?.removeEventListener('touchstart', handleTouchStart)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleDragEnd)
      window.removeEventListener('touchmove', handleTouchMove)
      window.removeEventListener('touchend', handleDragEnd)
      window.removeEventListener('touchcancel', handleDragEnd)
    }
  }, [])

  return (
    <div className="mana-rail-header" aria-label="Mana symbols">
      <div
        ref={railRef}
        className="mana-rail"
        role="toolbar"
        aria-label="Insert mana symbols"
      >
        {SYMBOLS.map((symbol, index) => {
          if (symbol === '.') {
            return (
              <span key={`divider-${index}`} className="mana-rail-divider" aria-hidden="true">
                •
              </span>
            )
          }

          const manaClass = getManaClass(symbol)

          return (
            <button
              key={symbol}
              type="button"
              className="mana-rail-button"
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
              {manaClass ? <i className={`${manaClass} ms-cost mana-rail-icon`} aria-hidden="true" /> : symbol}
            </button>
          )
        })}
      </div>
    </div>
  )
}
