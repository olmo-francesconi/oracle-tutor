import { useMemo } from 'react'
import { getManaClass, splitSymbolParts } from '../../lib/manaSymbols'

type ViewportSize = {
  width: number
  height: number
}

interface DenseTextBackgroundProps {
  texts: string[]
  viewport: ViewportSize
  isVisible: boolean
  leftInset?: number
}

const TARGET_LINE_COUNT = 64
const MIN_LINE_HEIGHT_PX = 10
const CHARACTER_WIDTH_RATIO = 0.583
const LETTER_SPACING_EM = 0.008
const MIN_TEXT_LENGTH = 5000

function buildRepeatedText(texts: string[]): string {
  const joined = texts.join('  ·  ').trim()
  if (!joined) return ''

  let output = joined
  while (output.length < MIN_TEXT_LENGTH) {
    output += `  ·  ${joined}`
  }

  return output
}

function extendTextToLength(text: string, targetLength: number): string {
  if (!text) return ''
  if (text.length >= targetLength) return text

  let output = text
  while (output.length < targetLength) {
    output += `  ·  ${text}`
  }

  return output
}

function getBaseLineHeight(charCount: number): number {
  if (charCount > 7000) return 1.48
  if (charCount > 5500) return 1.52
  return 1.58
}

function renderBackgroundText(text: string) {
  return splitSymbolParts(text).map((part, index) => {
    if (part.startsWith('{') && part.endsWith('}')) {
      const manaClass = getManaClass(part)

      if (manaClass) {
        return (
          <i
            key={`symbol-${index}`}
            className={`${manaClass} ms-cost`}
            title={part}
            aria-label={part}
            style={{
              display: 'inline-block',
              fontSize: '0.9em',
              lineHeight: 1,
              verticalAlign: '-0.08em',
            }}
          />
        )
      }
    }

    return <span key={`text-${index}`}>{part}</span>
  })
}

export function DenseTextBackground({
  texts,
  viewport,
  isVisible,
  leftInset = 0,
}: DenseTextBackgroundProps) {
  const repeatedText = useMemo(() => buildRepeatedText(texts), [texts])

  const styles = useMemo(() => {
    const availableWidth = Math.max(viewport.width - leftInset, 1)
    const availableHeight = Math.max(viewport.height, 1)
    const lineHeightPx = Math.max(availableHeight / TARGET_LINE_COUNT, MIN_LINE_HEIGHT_PX)
    const baseLineHeight = getBaseLineHeight(repeatedText.length)
    const fontSizePx = lineHeightPx / baseLineHeight
    const characterWidthPx = fontSizePx * (CHARACTER_WIDTH_RATIO + LETTER_SPACING_EM)
    const charsPerRow = Math.max(Math.floor(availableWidth / characterWidthPx), 1)
    const visibleRows = Math.max(Math.floor(availableHeight / lineHeightPx), 1)
    const charsAvailable = visibleRows * charsPerRow

    return {
      fontSize: `${fontSizePx}px`,
      lineHeight: baseLineHeight,
      visibleText: extendTextToLength(repeatedText, charsAvailable),
    }
  }, [leftInset, repeatedText, viewport.height, viewport.width])

  return (
    <div
      className="pointer-events-none fixed inset-y-0 right-0 z-0 select-none overflow-hidden"
      style={{
        left: leftInset,
        contain: 'layout style paint',
        opacity: isVisible ? 1 : 0,
        transition: 'opacity 0.75s cubic-bezier(0.22, 0.03, 0.36, 1)',
      }}
      aria-hidden="true"
    >
      <p
        style={{
          margin: 0,
          width: '100%',
          height: '100%',
          overflow: 'hidden',
          fontFamily: "'DM Mono', monospace",
          color: '#111111',
          opacity: 0.088,
          wordBreak: 'break-all',
          overflowWrap: 'normal',
          fontSize: styles.fontSize,
          lineHeight: styles.lineHeight,
          letterSpacing: `${LETTER_SPACING_EM}em`,
        }}
      >
        {renderBackgroundText(styles.visibleText)}
      </p>
    </div>
  )
}
