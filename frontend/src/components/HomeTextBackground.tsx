import { useEffect, useMemo, useRef, useState } from 'react'
import { getManaClass, splitSymbolParts } from '../lib/manaSymbols'

type HomeTextBackgroundProps = {
  texts: string[]
  isLoaded: boolean
  leftInset?: number
  minTotalWidth?: number
  fitToParent?: boolean
  onStatsChange?: (stats: HomeTextBackgroundStats) => void
}

type ViewportSize = {
  width: number
  height: number
}

type TextMetrics = {
  charCount: number
  baseLineHeight: number
  text: string
}

export type HomeTextBackgroundStats = {
  viewportWidth: number
  viewportHeight: number
  rows: number
  visibleRows: number
  renderedLineHeightPx: number
  fontSizePx: number
  charsPerRow: number
  charsAvailable: number
  charTotal: number
}

const DEFAULT_VIEWPORT: ViewportSize = { width: 1280, height: 900 }
const DEFAULT_TEXT_METRICS: TextMetrics = {
  charCount: 5000,
  baseLineHeight: 1.58,
  text: '',
}
const TARGET_LINE_COUNT = 64
const MIN_LINE_HEIGHT_PX = 10
const CHARACTER_WIDTH_RATIO = 0.583
const LETTER_SPACING_EM = 0.008

function buildRepeatedText(texts: string[]): string {
  const joined = texts.join('  ·  ').trim()
  if (!joined) return ''

  let output = joined
  while (output.length < DEFAULT_TEXT_METRICS.charCount) {
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

function estimateMetrics(text: string): TextMetrics {
  if (!text) return DEFAULT_TEXT_METRICS

  const charCount = text.length
  const baseLineHeight = charCount > 7000 ? 1.48 : charCount > 5500 ? 1.52 : 1.58

  return {
    charCount,
    baseLineHeight,
    text,
  }
}

function renderBackgroundText(text: string) {
  const parts = splitSymbolParts(text)

  return parts.map((part, index) => {
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

export function HomeTextBackground({
  texts,
  isLoaded,
  leftInset = 0,
  minTotalWidth = 0,
  fitToParent = false,
  onStatsChange,
}: HomeTextBackgroundProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const frameRef = useRef<number | null>(null)
  const [viewport, setViewport] = useState<ViewportSize>(DEFAULT_VIEWPORT)

  useEffect(() => {
    if (fitToParent) {
      const node = containerRef.current
      if (!node) return

      const updateViewport = () => {
        const parent = node.parentElement
        if (!parent) return

        const totalWidth = Math.max(parent.clientWidth, minTotalWidth)
        setViewport({
          width: Math.max(totalWidth - leftInset, 0),
          height: Math.max(parent.clientHeight, 0),
        })
      }

      updateViewport()

      const observer = new ResizeObserver(() => updateViewport())
      observer.observe(node.parentElement ?? node)

      return () => observer.disconnect()
    }

    const updateViewport = () => {
      const vw = window.innerWidth
      // Use screen.height to match 100lvh (full physical screen) so text fills
      // edge-to-edge, regardless of browser chrome visibility.
      const vh = Math.max(window.innerHeight, window.screen?.height ?? 0)
      const totalWidth = Math.max(vw, minTotalWidth)
      setViewport({
        width: Math.max(totalWidth - leftInset, 0),
        height: Math.max(vh, 0),
      })
    }

    const scheduleUpdate = () => {
      if (frameRef.current !== null) return

      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null
        updateViewport()
      })
    }

    updateViewport()

    window.addEventListener('resize', scheduleUpdate)

    return () => {
      window.removeEventListener('resize', scheduleUpdate)
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current)
      }
    }
  }, [fitToParent, leftInset, minTotalWidth])

  const metrics = useMemo(() => {
    return estimateMetrics(buildRepeatedText(texts))
  }, [texts])

  const styles = useMemo(() => {
    const availableHeight = Math.max(viewport.height, 1)
    const lineHeightPx = Math.max(availableHeight / TARGET_LINE_COUNT, MIN_LINE_HEIGHT_PX)
    const fontSize = lineHeightPx / metrics.baseLineHeight
    const characterWidthPx = fontSize * (CHARACTER_WIDTH_RATIO + LETTER_SPACING_EM)
    const charsPerRow = Math.max(Math.floor(viewport.width / characterWidthPx), 1)
    const visibleRows = Math.max(Math.floor(availableHeight / lineHeightPx), 1)
    const charsAvailable = visibleRows * charsPerRow
    const visibleText = extendTextToLength(metrics.text, charsAvailable)

    return {
      charsPerRow,
      charsAvailable,
      fontSize: `${fontSize}px`,
      fontSizePx: fontSize,
      lineHeight: metrics.baseLineHeight,
      lineHeightPx,
      visibleRows,
      visibleText,
    }
  }, [metrics, viewport])

  useEffect(() => {
    if (!onStatsChange) return

    onStatsChange({
      viewportWidth: viewport.width,
      viewportHeight: viewport.height,
      rows: TARGET_LINE_COUNT,
      visibleRows: styles.visibleRows,
      renderedLineHeightPx: styles.lineHeightPx,
      fontSizePx: styles.fontSizePx,
      charsPerRow: styles.charsPerRow,
      charsAvailable: styles.charsAvailable,
      charTotal: metrics.charCount,
    })
  }, [metrics.charCount, onStatsChange, styles, viewport])

  return (
    <div
      ref={containerRef}
      className="pointer-events-none absolute inset-y-0 right-0 z-[1] select-none overflow-hidden"
      style={{
        left: leftInset,
        contain: 'layout style paint',
        opacity: isLoaded ? 1 : 0,
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
