import { useMemo } from 'react'
import type { CSSProperties } from 'react'
import { SymbolText } from '../SymbolText'

type ViewportSize = {
  width: number
  height: number
}

interface HomeEditorialTextProps {
  texts: string[]
  terms: string[]
  viewport: ViewportSize
  isVisible: boolean
  leftInset?: number
}

const PHRASE_SLOTS: Array<{ style: CSSProperties; color: string; opacity: number; baseFontSize?: number }> = [
  { style: { top: '7%', left: '2%' }, color: '#CC1100', opacity: 0.22 },
  { style: { top: '18%', right: '3%', textAlign: 'right' }, color: '#0E2150', opacity: 0.2 },
  { style: { top: '55%', left: '2.5%' }, color: '#F5C400', opacity: 0.28 },
  { style: { top: '68%', right: '4%', textAlign: 'right' }, color: '#CC1100', opacity: 0.22, baseFontSize: 20 },
  { style: { bottom: '6%', left: '2%' }, color: '#0E2150', opacity: 0.2, baseFontSize: 17 },
  { style: { top: '33%', left: '38%' }, color: '#F5C400', opacity: 0.28, baseFontSize: 15 },
]

const MONUMENT_SLOTS: Array<{ style: CSSProperties; baseFontSize: number }> = [
  {
    style: { color: '#CC1100', opacity: 0.085, top: '-2%', left: '-6px' },
    baseFontSize: 175,
  },
  {
    style: { color: '#F5C400', opacity: 0.14, top: '37%', right: '-24px' },
    baseFontSize: 108,
  },
  {
    style: { color: '#0E2150', opacity: 0.1, bottom: '-4%', left: '-4px' },
    baseFontSize: 126,
  },
]

const MAX_MONUMENT_TERM_LENGTH = 18
const DESIGN_VIEWPORT_WIDTH = 1440
const DESIGN_VIEWPORT_HEIGHT = 900
const MIN_COMPOSITION_SCALE = 0.78
const MAX_COMPOSITION_SCALE = 1.18
const DEFAULT_PHRASE_FONT_SIZE = 24

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function HomeEditorialText({
  texts,
  terms,
  viewport,
  isVisible,
  leftInset = 0,
}: HomeEditorialTextProps) {
  const phraseTexts = useMemo(() => {
    if (texts.length === 0) return []

    const shortTexts = texts.filter((text) => text.length < 90)
    const pool = shortTexts.length >= PHRASE_SLOTS.length ? shortTexts : [...shortTexts, ...texts]
    return pool.slice(0, PHRASE_SLOTS.length)
  }, [texts])

  const monumentTerms = useMemo(() => {
    const safeTerms = terms.filter((term) => term.length > 0 && term.length <= MAX_MONUMENT_TERM_LENGTH)
    return Array.from(new Set(safeTerms)).slice(0, MONUMENT_SLOTS.length)
  }, [terms])

  const compositionScale = useMemo(() => {
    const availableWidth = Math.max(viewport.width - leftInset, 1)
    const widthRatio = availableWidth / DESIGN_VIEWPORT_WIDTH
    const heightRatio = Math.max(viewport.height, 1) / DESIGN_VIEWPORT_HEIGHT
    return clamp(Math.min(widthRatio, heightRatio), MIN_COMPOSITION_SCALE, MAX_COMPOSITION_SCALE)
  }, [leftInset, viewport.height, viewport.width])

  return (
    <div
      className="pointer-events-none fixed inset-y-0 right-0 z-10 select-none overflow-hidden"
      style={{
        left: leftInset,
        opacity: isVisible ? 1 : 0,
        transition: 'opacity 0.75s cubic-bezier(0.22, 0.03, 0.36, 1) 0.35s',
      }}
      aria-hidden="true"
    >
      {MONUMENT_SLOTS.map(({ style, baseFontSize }, index) => (
        <span
          key={monumentTerms[index] ?? `monument-${index}`}
          style={{
            position: 'absolute',
            fontFamily: "'Big Shoulders Display', sans-serif",
            fontWeight: 900,
            textTransform: 'uppercase',
            lineHeight: 0.88,
            letterSpacing: '-0.025em',
            whiteSpace: 'nowrap',
            fontSize: `${baseFontSize * compositionScale}px`,
            ...style,
          }}
        >
          {monumentTerms[index] ?? ''}
        </span>
      ))}

      {PHRASE_SLOTS.map((slot, index) => (
        <div
          key={`phrase-${index}`}
          style={{
            position: 'absolute',
            fontFamily: "'DM Mono', monospace",
            fontWeight: 500,
            fontSize: `${(slot.baseFontSize ?? DEFAULT_PHRASE_FONT_SIZE) * compositionScale}px`,
            lineHeight: '1.28',
            letterSpacing: '-0.008em',
            maxWidth: '45%',
            whiteSpace: 'pre-wrap',
            color: slot.color,
            opacity: slot.opacity,
            ...slot.style,
          }}
        >
          <SymbolText text={phraseTexts[index] ?? ''} />
        </div>
      ))}
    </div>
  )
}
