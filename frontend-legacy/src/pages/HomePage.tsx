import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { DeveloperLinks } from '../components/DeveloperLinks'
import { HomeTextBackground, type HomeTextBackgroundStats } from '../components/HomeTextBackground'
import { PageSEO } from '../components/PageSEO'
import { SymbolText } from '../components/SymbolText'
import { UnifiedSearchBox } from '../components/UnifiedSearchBox'
import { DEFAULT_DESCRIPTION, DEFAULT_TITLE } from '../lib/seo'
import { getOracleSamples } from '../api'

// Six hand-placed oracle phrase positions — Bauhaus primary triad: red, yellow, cobalt blue
const PHRASE_SLOTS: Array<{ style: React.CSSProperties; color: string; opacity: number; baseFontSize?: number }> = [
  { style: { top: '7%',    left:  '2%'  },                                                          color: '#CC1100', opacity: 0.22 },
  { style: { top: '18%',   right: '3%',  textAlign: 'right' },                                      color: '#0E2150', opacity: 0.20 },
  { style: { top: '55%',   left:  '2.5%' },                                                         color: '#F5C400', opacity: 0.28 },
  { style: { top: '68%',   right: '4%',  textAlign: 'right' },                                      color: '#CC1100', opacity: 0.22, baseFontSize: 20 },
  { style: { bottom: '6%', left:  '2%' },                                                           color: '#0E2150', opacity: 0.20, baseFontSize: 17 },
  { style: { top: '33%',   left: '38%' },                                                           color: '#F5C400', opacity: 0.28, baseFontSize: 15 },
]

const MONUMENT_SLOTS: Array<{ style: React.CSSProperties; baseFontSize: number }> = [
  {
    style: { color: '#CC1100', opacity: 0.085, top: '-2%',    left: '-6px'  } as React.CSSProperties,
    baseFontSize: 175,
  },
  {
    style: { color: '#F5C400', opacity: 0.14,  top: '37%',    right: '-24px' } as React.CSSProperties,
    baseFontSize: 108,
  },
  {
    style: { color: '#0E2150', opacity: 0.10, bottom: '-4%', left: '-4px'  } as React.CSSProperties,
    baseFontSize: 126,
  },
]
const MAX_MONUMENT_TERM_LENGTH = 18
const HOME_LEFT_INSET = 6
const MIN_HOME_COMPOSITION_WIDTH = 360
const DESIGN_VIEWPORT_WIDTH = 1440
const DESIGN_VIEWPORT_HEIGHT = 900
const MIN_COMPOSITION_SCALE = 0.78
const MAX_COMPOSITION_SCALE = 1.18
const WORDMARK_BASE_FONT_SIZE = 92
const WORDMARK_MIN_FONT_SIZE = 72
const WORDMARK_MAX_FONT_SIZE = 109
const HERO_MAX_WIDTH = 560
const HERO_MOBILE_MAX_WIDTH = 680
const HERO_STACK_GAP = 40
const HERO_OPEN_TOP_VIEWPORT = 0.11
const HERO_FOCUS_OFFSET = 28
const HERO_TITLE_OFFSET = 18
const HERO_DIVIDER_MARGIN = 14
const HERO_DIVIDER_HEIGHT = 2
const HERO_SUBTITLE_FONT_SIZE = 13
const HERO_PHRASE_FONT_SIZE = 24
const FOOTER_RIGHT_INSET = 40
const FOOTER_BOTTOM_INSET = 20
const FOOTER_SCALE_MIN = 0.92
const FOOTER_SCALE_MAX = 1.05
const FOOTER_DOCUMENT_CLEARANCE = 52
const HERO_BOTTOM_CLEARANCE = 88
const HERO_SIDE_CLEARANCE = 20
const BACKGROUND_STAGE_OVERSCAN_VIEWPORTS = 0.5
const BACKGROUND_STAGE_HEIGHT_VIEWPORTS = 1 + BACKGROUND_STAGE_OVERSCAN_VIEWPORTS * 2
const MOBILE_TRANSITION_START = 768
const MOBILE_TRANSITION_END = 520

type HomeViewport = {
  width: number
  height: number
}

const DEFAULT_VIEWPORT: HomeViewport = {
  width: DESIGN_VIEWPORT_WIDTH - HOME_LEFT_INSET,
  height: DESIGN_VIEWPORT_HEIGHT,
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function lerp(start: number, end: number, amount: number): number {
  return start + (end - start) * amount
}

const SHOW_HOME_BACKGROUND_DEBUG_PANEL = false

function HomeBackgroundDebugPanel({ stats }: { stats: HomeTextBackgroundStats }) {
  return (
    <div className="fixed right-4 top-4 z-50 border border-[#111111]/15 bg-[#F0EDE6]/92 px-3 py-2 font-mono text-[11px] leading-[1.45] text-[#111111] backdrop-blur-sm">
      <p>viewport_size: {stats.viewportWidth} x {stats.viewportHeight}</p>
      <p>rows: {stats.rows}</p>
      <p>visible_rows: {stats.visibleRows}</p>
      <p>line_height: {stats.renderedLineHeightPx.toFixed(2)}px</p>
      <p>font_size: {stats.fontSizePx.toFixed(2)}px</p>
      <p>char_per_row: {stats.charsPerRow}</p>
      <p>char_available: {stats.charsAvailable}</p>
      <p>char_total: {stats.charTotal}</p>
    </div>
  )
}

export default function HomePage() {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const [dropdownBottom, setDropdownBottom] = useState(0)
  const [isSearchFocused, setIsSearchFocused] = useState(false)
  const [openHeroMove, setOpenHeroMove] = useState(0)
  const [backgroundStats, setBackgroundStats] = useState<HomeTextBackgroundStats | null>(null)
  const [viewport, setViewport] = useState<HomeViewport>(DEFAULT_VIEWPORT)
  const frameRef = useRef<number | null>(null)
  const heroBlockRef = useRef<HTMLDivElement | null>(null)
  const heroTitleRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const updateViewport = () => {
      setViewport({
        width: Math.max(window.innerWidth - HOME_LEFT_INSET, 0),
        height: Math.max(window.innerHeight, 0),
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
  }, [])

  useLayoutEffect(() => {
    document.documentElement.classList.add('homepage-root-scroll-lock')
    document.documentElement.classList.add('homepage-scroll-hidden')
    document.body.classList.add('homepage-root-scroll-lock')
    document.body.classList.add('homepage-scroll-hidden')

    return () => {
      document.documentElement.classList.remove('homepage-root-scroll-lock')
      document.documentElement.classList.remove('homepage-scroll-hidden')
      document.body.classList.remove('homepage-root-scroll-lock')
      document.body.classList.remove('homepage-scroll-hidden')
    }
  }, [])

  // Fetch once per session. No fallback — layers are invisible until data arrives.
  const { data: oracleSamples, isSuccess } = useQuery({
    queryKey: ['oracle-samples'],
    queryFn: getOracleSamples,
    staleTime: Infinity,
    gcTime: Infinity,
  })

  const texts = useMemo(() => oracleSamples?.texts ?? [], [oracleSamples])
  const terms = useMemo(() => oracleSamples?.terms ?? [], [oracleSamples])
  const isLoaded = isSuccess && texts.length > 0

  // Medium phrases: pick up to 6 short texts (< 90 chars) from the random pool
  const phraseTexts = useMemo(() => {
    if (texts.length === 0) return []
    const short = texts.filter((t) => t.length < 90)
    const pool = short.length >= 6 ? short : [...short, ...texts]
    return pool.slice(0, 6)
  }, [texts])

  const monumentTerms = useMemo(() => {
    const safeTerms = terms.filter((term) => term.length > 0 && term.length <= MAX_MONUMENT_TERM_LENGTH)
    const uniqueTerms = Array.from(new Set(safeTerms))
    return uniqueTerms.slice(0, MONUMENT_SLOTS.length)
  }, [terms])

  const compositionScale = useMemo(() => {
    const widthRatio = viewport.width / DESIGN_VIEWPORT_WIDTH
    const heightRatio = viewport.height / DESIGN_VIEWPORT_HEIGHT
    return clamp(Math.min(widthRatio, heightRatio), MIN_COMPOSITION_SCALE, MAX_COMPOSITION_SCALE)
  }, [viewport])
  const mobileTransitionProgress = clamp(
    (MOBILE_TRANSITION_START - viewport.width) / (MOBILE_TRANSITION_START - MOBILE_TRANSITION_END),
    0,
    1
  )
  const wordmarkMinFontSize = lerp(WORDMARK_MIN_FONT_SIZE, 62, mobileTransitionProgress)
  const heroMaxWidth = lerp(HERO_MAX_WIDTH, HERO_MOBILE_MAX_WIDTH, mobileTransitionProgress)
  const heroGapBase = lerp(HERO_STACK_GAP, 34, mobileTransitionProgress)
  const heroBottomClearanceBase = lerp(HERO_BOTTOM_CLEARANCE, 36, mobileTransitionProgress)

  const wordmarkFontSize = clamp(
    WORDMARK_BASE_FONT_SIZE * compositionScale,
    wordmarkMinFontSize,
    WORDMARK_MAX_FONT_SIZE
  )
  const heroWidth = Math.min(
    heroMaxWidth * compositionScale,
    Math.max(viewport.width - 32, 0)
  )
  const heroStackGap = heroGapBase * compositionScale
  const focusOffset = HERO_FOCUS_OFFSET * compositionScale
  const titleOffset = HERO_TITLE_OFFSET * compositionScale
  const dividerMargin = HERO_DIVIDER_MARGIN * compositionScale
  const dividerHeight = HERO_DIVIDER_HEIGHT * compositionScale
  const subtitleFontSize = HERO_SUBTITLE_FONT_SIZE * compositionScale
  const footerRightInset = FOOTER_RIGHT_INSET * compositionScale
  const footerBottomInset = FOOTER_BOTTOM_INSET * compositionScale
  const footerScale = clamp(compositionScale, FOOTER_SCALE_MIN, FOOTER_SCALE_MAX)
  const footerDocumentClearance = FOOTER_DOCUMENT_CLEARANCE * footerScale
  const heroBottomClearance = heroBottomClearanceBase * compositionScale
  const heroSideClearance = HERO_SIDE_CLEARANCE * compositionScale
  const backgroundStageOffset = `${BACKGROUND_STAGE_OVERSCAN_VIEWPORTS * 100}lvh`
  const backgroundStageHeight = `${BACKGROUND_STAGE_HEIGHT_VIEWPORTS * 100}lvh`
  const dropdownOverflow = Math.max(dropdownBottom - viewport.height, 0)
  const homepageDocumentExtension = dropdownOverflow > 0 ? dropdownOverflow + footerDocumentClearance : 0

  useLayoutEffect(() => {
    if (!isDropdownOpen) {
      setOpenHeroMove(0)
      return
    }

    const heroBlockRect = heroBlockRef.current?.getBoundingClientRect()
    const heroTitleRect = heroTitleRef.current?.getBoundingClientRect()
    if (!heroBlockRect || !heroTitleRect) return

    const targetTop = viewport.height * HERO_OPEN_TOP_VIEWPORT
    const safeTitleTop = Math.max(24, wordmarkFontSize * 0.28)
    const requiredMove = Math.max(heroBlockRect.top - targetTop, 0)
    const maxMove = Math.max(heroTitleRect.top - safeTitleTop, 0)
    const nextMove = Math.min(requiredMove, maxMove)

    if (Math.abs(nextMove - openHeroMove) > 0.5) {
      setOpenHeroMove(nextMove)
    }
  }, [isDropdownOpen, openHeroMove, viewport.height, viewport.width, wordmarkFontSize])

  return (
    <div className="relative h-[100svh] overflow-hidden">
      <PageSEO
        title={DEFAULT_TITLE}
        description={DEFAULT_DESCRIPTION}
        path="/"
      />

      <div
        className="homepage-scroll-container relative h-full overflow-x-hidden overflow-y-auto"
        style={{ paddingBottom: homepageDocumentExtension }}
      >
        {/* Red left stripe */}
        <div
          className="absolute left-0 top-0 z-50 w-[6px] bg-[#CC1100]"
          style={{ height: `calc(100% + ${homepageDocumentExtension}px)` }}
        />

        <div
          className="pointer-events-none fixed left-[6px] right-0 z-[1] select-none overflow-hidden"
          style={{
            top: `calc(${backgroundStageOffset} * -1)`,
            height: backgroundStageHeight,
            contain: 'layout style paint',
          }}
        >
          <div
            className="absolute inset-x-0 h-[100lvh] overflow-hidden"
            style={{ top: backgroundStageOffset }}
          >
            <HomeTextBackground
              texts={texts}
              isLoaded={isLoaded}
              leftInset={0}
              minTotalWidth={MIN_HOME_COMPOSITION_WIDTH}
              fitToParent
              onStatsChange={setBackgroundStats}
            />

            <div
              className="absolute inset-0 z-[3] overflow-hidden"
              style={{
                opacity: isLoaded ? 1 : 0,
                transition: 'opacity 0.75s cubic-bezier(0.22, 0.03, 0.36, 1) 0.35s',
              }}
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
            </div>

            <div
              className="absolute inset-0 z-[2] overflow-hidden"
              style={{
                opacity: isLoaded ? 1 : 0,
                transition: 'opacity 0.75s cubic-bezier(0.22, 0.03, 0.36, 1) 0.75s',
              }}
            >
              {PHRASE_SLOTS.map((slot, i) => (
                <div
                  key={i}
                  style={{
                    position: 'absolute',
                    fontFamily: "'DM Mono', monospace",
                    fontWeight: 500,
                    fontSize: `${(slot.baseFontSize ?? HERO_PHRASE_FONT_SIZE) * compositionScale}px`,
                    lineHeight: '1.28',
                    letterSpacing: '-0.008em',
                    maxWidth: '45%',
                    color: slot.color,
                    opacity: slot.opacity,
                    ...slot.style,
                  }}
                >
                  <SymbolText
                    text={phraseTexts[i] ?? ''}
                    className="inline"
                    symbolClassName="align-[-0.08em]"
                    preserveLineBreaks
                  />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Foreground: wordmark + search — always visible, independent of oracle loading */}
        <div
          className="relative z-10 flex h-[100svh] min-h-[100svh] flex-col items-center justify-center pl-[6px]"
          style={{
            paddingBottom: `${heroBottomClearance}px`,
            paddingInline: `${heroSideClearance}px`,
          }}
        >
          <motion.div
            ref={heroBlockRef}
            className="flex w-full flex-col items-center"
            style={{ maxWidth: `${heroWidth}px`, gap: `${heroStackGap}px` }}
            animate={{ y: isDropdownOpen ? -openHeroMove : isSearchFocused ? -focusOffset : 0 }}
            transition={{ type: 'tween', ease: [0.22, 0.03, 0.36, 1], duration: 0.22 }}
          >
            <motion.div
              ref={heroTitleRef}
              className="w-fit animate-[fadeIn_0.4s_ease-out] text-center"
              animate={{ y: isSearchFocused ? -titleOffset : 0 }}
              transition={{ type: 'tween', ease: [0.22, 0.03, 0.36, 1], duration: 0.22 }}
            >
              <h1
                className="font-display font-[900] uppercase leading-[0.92] tracking-[-0.02em] text-[#111111]"
                style={{ fontSize: `${wordmarkFontSize}px` }}
              >
                Oracle<br />Tutor
              </h1>
              <div className="w-full bg-[#111111]" style={{ marginBlock: `${dividerMargin}px`, height: `${dividerHeight}px` }} />
              <p className="font-mono text-[#7A7670]" style={{ fontSize: `${subtitleFontSize}px` }}>
                find cards by meaning, not keywords.
              </p>
            </motion.div>

            <div
              className="w-full animate-[slideUp_0.4s_ease-out_0.15s] opacity-0"
              style={{ animationFillMode: 'forwards' }}
            >
              <UnifiedSearchBox
                autoFocus
                enableTypeAhead
                size="hero"
                heroScale={compositionScale}
                onDropdownChange={setIsDropdownOpen}
                onDropdownHeightChange={setDropdownBottom}
                onFocusChange={setIsSearchFocused}
              />
            </div>
          </motion.div>
          {SHOW_HOME_BACKGROUND_DEBUG_PANEL && backgroundStats ? (
            <HomeBackgroundDebugPanel stats={backgroundStats} />
          ) : null}
        </div>
      </div>

      <div
        className="pointer-events-none absolute inset-x-0 z-[5] flex justify-center md:justify-end"
        style={{
          bottom: `${footerBottomInset}px`,
          paddingInline: `${footerRightInset}px`,
        }}
      >
        <div
          className="pointer-events-auto"
          style={{
            transform: `scale(${footerScale})`,
            transformOrigin: 'bottom center',
          }}
        >
          <DeveloperLinks variant="dark" />
        </div>
      </div>
    </div>
  )
}
