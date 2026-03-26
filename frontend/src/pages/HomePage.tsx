import { useState, useMemo } from 'react'
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
const PHRASE_SLOTS: Array<{ style: React.CSSProperties; color: string; opacity: number }> = [
  { style: { top: '7%',    left:  '2%'  },                                                          color: '#CC1100', opacity: 0.22 },
  { style: { top: '18%',   right: '3%',  textAlign: 'right' },                                      color: '#0E2150', opacity: 0.20 },
  { style: { top: '55%',   left:  '2.5%' },                                                         color: '#F5C400', opacity: 0.28 },
  { style: { top: '68%',   right: '4%',  textAlign: 'right', fontSize: 'clamp(16px,1.9vw,24px)' }, color: '#CC1100', opacity: 0.22 },
  { style: { bottom: '6%', left:  '2%',  fontSize: 'clamp(14px,1.7vw,21px)' },                     color: '#0E2150', opacity: 0.20 },
  { style: { top: '33%',   left: '38%',  fontSize: 'clamp(13px,1.5vw,18px)' },                     color: '#F5C400', opacity: 0.28 },
]

const MONUMENT_SLOTS = [
  {
    style: { color: '#CC1100', fontSize: 'clamp(110px,17vw,230px)', opacity: 0.085, top: '-2%',    left: '-6px'  } as React.CSSProperties,
  },
  {
    style: { color: '#F5C400', fontSize: 'clamp(75px,10vw,140px)',  opacity: 0.14,  top: '37%',    right: '-24px' } as React.CSSProperties,
  },
  {
    style: { color: '#0E2150', fontSize: 'clamp(88px,12.5vw,165px)', opacity: 0.10, bottom: '-4%', left: '-4px'  } as React.CSSProperties,
  },
]
const MAX_MONUMENT_TERM_LENGTH = 18

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
  const [isSearchFocused, setIsSearchFocused] = useState(false)
  const [backgroundStats, setBackgroundStats] = useState<HomeTextBackgroundStats | null>(null)

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

  return (
    <>
      <PageSEO
        title={DEFAULT_TITLE}
        description={DEFAULT_DESCRIPTION}
        path="/"
      />

      {/* Red left stripe */}
      <div className="fixed left-0 top-0 z-50 h-full w-[6px] bg-[#CC1100]" />

      <HomeTextBackground
        texts={texts}
        isLoaded={isLoaded}
        leftInset={6}
        onStatsChange={setBackgroundStats}
      />

      {/* ── Art layer 2: Monumental keywords ───────────────────────────────────
          Fades in second (0.35s delay). Letter-shapes emerge as abstract forms. */}
      <div
        className="pointer-events-none fixed inset-0 z-[3] select-none overflow-hidden"
        style={{
          left: 6,
          contain: 'layout style',
          opacity: isLoaded ? 1 : 0,
          transition: 'opacity 0.75s cubic-bezier(0.22, 0.03, 0.36, 1) 0.35s',
        }}
      >
        {MONUMENT_SLOTS.map(({ style }, index) => (
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
              ...style,
            }}
          >
            {monumentTerms[index] ?? ''}
          </span>
        ))}
      </div>

      {/* ── Art layer 3: Medium oracle phrases ─────────────────────────────────
          Fades in last (0.75s delay). Fine type settles over the composition. */}
      <div
        className="pointer-events-none fixed inset-0 z-[2] select-none overflow-hidden"
        style={{
          left: 6,
          contain: 'layout style',
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
              fontSize: 'clamp(19px,2.3vw,29px)',
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

      {/* Foreground: wordmark + search — always visible, independent of oracle loading */}
      <div className="relative z-10 flex min-h-screen flex-col items-center justify-center pl-[6px]">
        <motion.div
          className="flex w-full max-w-[560px] flex-col items-center"
          animate={{ y: isDropdownOpen ? -56 : isSearchFocused ? -28 : 0 }}
          transition={{ type: 'tween', ease: [0.22, 0.03, 0.36, 1], duration: 0.22 }}
        >
          <motion.div
            className="mb-10 w-fit animate-[fadeIn_0.4s_ease-out] text-center"
            animate={{ y: isSearchFocused ? -18 : 0 }}
            transition={{ type: 'tween', ease: [0.22, 0.03, 0.36, 1], duration: 0.22 }}
          >
            <h1
              className="font-display font-[900] uppercase leading-[0.92] tracking-[-0.02em] text-[#111111]"
              style={{ fontSize: 'clamp(64px, 12vw, 108px)' }}
            >
              Oracle<br />Tutor
            </h1>
            <div className="my-[14px] h-[2px] w-full bg-[#111111]" />
            <p className="font-mono text-[13px] text-[#7A7670]">
              find cards by meaning, not keywords.
            </p>
          </motion.div>

          <div
            className="w-full animate-[slideUp_0.4s_ease-out_0.15s] opacity-0"
            style={{ animationFillMode: 'forwards' }}
          >
            <UnifiedSearchBox
              autoFocus
              onDropdownChange={setIsDropdownOpen}
              onFocusChange={setIsSearchFocused}
            />
          </div>
        </motion.div>

        <div className="fixed bottom-5 right-10">
          <DeveloperLinks variant="dark" />
        </div>

        {SHOW_HOME_BACKGROUND_DEBUG_PANEL && backgroundStats ? (
          <HomeBackgroundDebugPanel stats={backgroundStats} />
        ) : null}
      </div>
    </>
  )
}
