import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { DeveloperLinks } from '../components/DeveloperLinks'
import { PageSEO } from '../components/PageSEO'
import { UnifiedSearchBox } from '../components/UnifiedSearchBox'
import { DEFAULT_DESCRIPTION, DEFAULT_TITLE } from '../lib/seo'
import { getOracleSamples } from '../api'

// Easing shared across all art layer transitions — same curve used elsewhere in the app
const ART_EASE = [0.22, 0.03, 0.36, 1] as const

// Six hand-placed oracle phrase positions — Bauhaus primary triad: red, yellow, cobalt blue
const PHRASE_SLOTS: Array<{ style: React.CSSProperties; color: string; opacity: number }> = [
  { style: { top: '7%',    left:  '2%'  },                                                          color: '#CC1100', opacity: 0.22 },
  { style: { top: '18%',   right: '3%',  textAlign: 'right' },                                      color: '#0E2150', opacity: 0.20 },
  { style: { top: '55%',   left:  '2.5%' },                                                         color: '#F5C400', opacity: 0.28 },
  { style: { top: '68%',   right: '4%',  textAlign: 'right', fontSize: 'clamp(16px,1.9vw,24px)' }, color: '#CC1100', opacity: 0.22 },
  { style: { bottom: '6%', left:  '2%',  fontSize: 'clamp(14px,1.7vw,21px)' },                     color: '#0E2150', opacity: 0.20 },
  { style: { top: '33%',   left: '38%',  fontSize: 'clamp(13px,1.5vw,18px)' },                     color: '#F5C400', opacity: 0.28 },
]

// Monumental keywords — each one a Bauhaus primary, partially cropped at viewport edges
const MONUMENTS = [
  {
    word: 'DEATHTOUCH',
    style: { color: '#CC1100', fontSize: 'clamp(110px,17vw,230px)', opacity: 0.085, top: '-2%',    left: '-6px'  } as React.CSSProperties,
  },
  {
    word: 'VIGILANCE',
    style: { color: '#F5C400', fontSize: 'clamp(75px,10vw,140px)',  opacity: 0.14,  top: '37%',    right: '-24px' } as React.CSSProperties,
  },
  {
    word: 'INDESTRUCTIBLE',
    style: { color: '#0E2150', fontSize: 'clamp(88px,12.5vw,165px)', opacity: 0.10, bottom: '-4%', left: '-4px'  } as React.CSSProperties,
  },
]

export default function HomePage() {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)

  // Fetch once per session. No fallback — layers are invisible until data arrives.
  const { data: oracleSamples, isSuccess } = useQuery({
    queryKey: ['oracle-samples'],
    queryFn: getOracleSamples,
    staleTime: Infinity,
    gcTime: Infinity,
  })

  const texts = oracleSamples ?? []
  const isLoaded = isSuccess && texts.length > 0

  // Micro ground: enough rows to fill the viewport, each staggered by offset into the text pool
  const groundRows = useMemo(() => {
    if (texts.length === 0) return []
    const joined = texts.join('  ·  ')
    const rowCount = Math.ceil((typeof window !== 'undefined' ? window.innerHeight : 900) / 15) + 4
    return Array.from({ length: rowCount }, (_, i) => {
      const off = (i * 53) % joined.length
      return (joined.slice(off) + '  ·  ' + joined).repeat(4)
    })
  }, [texts])

  // Medium phrases: pick up to 6 short texts (< 90 chars) from the random pool
  const phraseTexts = useMemo(() => {
    if (texts.length === 0) return []
    const short = texts.filter((t) => t.length < 90)
    const pool = short.length >= 6 ? short : [...short, ...texts]
    return pool.slice(0, 6)
  }, [texts])

  // Shared transition factory — same duration and easing, only delay differs
  const layerTransition = (delay: number) => ({
    duration: 0.75,
    ease: ART_EASE,
    delay,
  })

  return (
    <>
      <PageSEO
        title={DEFAULT_TITLE}
        description={DEFAULT_DESCRIPTION}
        path="/"
      />

      {/* Red left stripe */}
      <div className="fixed left-0 top-0 z-50 h-full w-[6px] bg-[#CC1100]" />

      {/* ── Art layer 1: Micro oracle text ground ──────────────────────────────
          Fades in first. Container opacity compounds with children's 0.088,
          so each row fades from invisible to its target artistic opacity. */}
      <motion.div
        className="pointer-events-none fixed inset-0 z-[1] select-none overflow-hidden"
        style={{ left: 6 }}
        initial={{ opacity: 0 }}
        animate={{ opacity: isLoaded ? 1 : 0 }}
        transition={layerTransition(0)}
      >
        {groundRows.map((row, i) => (
          <p
            key={i}
            style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: '9.5px',
              lineHeight: '1.58',
              color: '#111111',
              opacity: 0.088,
              letterSpacing: '0.008em',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
          >
            {row}
          </p>
        ))}
      </motion.div>

      {/* ── Art layer 2: Monumental keywords ───────────────────────────────────
          Fades in second (0.35s delay). Letter-shapes emerge as abstract forms. */}
      <motion.div
        className="pointer-events-none fixed inset-0 z-[3] select-none overflow-hidden"
        style={{ left: 6 }}
        initial={{ opacity: 0 }}
        animate={{ opacity: isLoaded ? 1 : 0 }}
        transition={layerTransition(0.35)}
      >
        {MONUMENTS.map(({ word, style }) => (
          <span
            key={word}
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
            {word}
          </span>
        ))}
      </motion.div>

      {/* ── Art layer 3: Medium oracle phrases ─────────────────────────────────
          Fades in last (0.75s delay). Fine type settles over the composition. */}
      <motion.div
        className="pointer-events-none fixed inset-0 z-[2] select-none overflow-hidden"
        style={{ left: 6 }}
        initial={{ opacity: 0 }}
        animate={{ opacity: isLoaded ? 1 : 0 }}
        transition={layerTransition(0.75)}
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
            {phraseTexts[i] ?? ''}
          </div>
        ))}
      </motion.div>

      {/* Foreground: wordmark + search — always visible, independent of oracle loading */}
      <div className="relative z-10 flex min-h-screen flex-col items-center justify-center pl-[6px]">
        <motion.div
          className="flex w-full max-w-[560px] flex-col items-center"
          animate={{ y: isDropdownOpen ? -56 : 0 }}
          transition={{ type: 'tween', ease: [0.22, 0.03, 0.36, 1], duration: 0.22 }}
        >
          <div className="mb-10 w-fit animate-[fadeIn_0.4s_ease-out] text-center">
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
          </div>

          <div
            className="w-full animate-[slideUp_0.4s_ease-out_0.15s] opacity-0"
            style={{ animationFillMode: 'forwards' }}
          >
            <UnifiedSearchBox autoFocus onDropdownChange={setIsDropdownOpen} />
          </div>
        </motion.div>

        <div className="fixed bottom-5 left-10">
          <DeveloperLinks variant="dark" />
        </div>
      </div>
    </>
  )
}
