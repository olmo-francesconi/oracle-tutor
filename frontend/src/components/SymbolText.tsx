import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { cn } from '../lib/cn'

const TOKEN_RE = /\{([^}]+)\}/g

type SymbologySymbol = {
  symbol: string
  svg_uri: string
  english?: string
}

type SymbologyResponse = {
  data: SymbologySymbol[]
}

const LS_KEY = 'scryfall_symbology_v1'
const LS_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 14 // 14 days

let symbologyPromise: Promise<Map<string, SymbologySymbol>> | null = null

function loadSymbology(): Promise<Map<string, SymbologySymbol>> {
  if (symbologyPromise) return symbologyPromise

  symbologyPromise = (async () => {
    // Try cached mapping first
    try {
      const raw = localStorage.getItem(LS_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as {
          ts: number
          symbols: SymbologySymbol[]
        }
        if (
          parsed?.ts &&
          Array.isArray(parsed.symbols) &&
          Date.now() - parsed.ts < LS_MAX_AGE_MS
        ) {
          return new Map(parsed.symbols.map((s) => [s.symbol, s]))
        }
      }
    } catch {
      // ignore cache parse errors
    }

    const res = await fetch('https://api.scryfall.com/symbology', {
      headers: { accept: 'application/json' },
    })
    if (!res.ok) throw new Error(`Scryfall symbology fetch failed: ${res.status}`)
    const json = (await res.json()) as SymbologyResponse
    const symbols = Array.isArray(json.data) ? json.data : []

    try {
      localStorage.setItem(
        LS_KEY,
        JSON.stringify({ ts: Date.now(), symbols })
      )
    } catch {
      // ignore quota errors
    }

    return new Map(symbols.map((s) => [s.symbol, s]))
  })()

  return symbologyPromise
}

export type SymbolTextProps = {
  text?: string | null
  className?: string
  /** Extra classes applied to each `<img>` glyph. */
  symbolClassName?: string
  /** Controls symbol height relative to current font size. */
  sizeEm?: number
}

export function SymbolText({
  text,
  className,
  symbolClassName,
  sizeEm = 1.05,
}: SymbolTextProps) {
  const [map, setMap] = useState<Map<string, SymbologySymbol> | null>(null)

  useEffect(() => {
    let cancelled = false
    loadSymbology()
      .then((m) => {
        if (!cancelled) setMap(m)
      })
      .catch(() => {
        if (!cancelled) setMap(new Map())
      })
    return () => {
      cancelled = true
    }
  }, [])

  const nodes = useMemo((): ReactNode => {
    if (!text) return null

    const out: ReactNode[] = []
    let symbolRun: ReactNode[] = []
    let runId = 0

    const flushRun = () => {
      if (symbolRun.length === 0) return
      out.push(
        <span
          key={`symrun-${runId++}`}
          className="inline-flex whitespace-nowrap align-text-bottom"
        >
          {symbolRun}
        </span>
      )
      symbolRun = []
    }

    let lastIndex = 0
    let match: RegExpExecArray | null

    while ((match = TOKEN_RE.exec(text)) !== null) {
      const fullMatch = match[0] // e.g. "{G}"
      const startIndex = match.index
      const endIndex = startIndex + fullMatch.length

      if (startIndex > lastIndex) {
        flushRun()
        out.push(text.slice(lastIndex, startIndex))
      }

      const sym = map?.get(fullMatch)
      if (!sym) {
        // If map isn't loaded yet, or symbol unknown, keep the original token.
        flushRun()
        out.push(fullMatch)
      } else {
        const alt = sym.english || fullMatch
        symbolRun.push(
          <img
            key={`sym-${startIndex}-${sym.symbol}`}
            src={sym.svg_uri}
            alt={alt}
            title={alt}
            className={cn('inline-block align-text-bottom', symbolClassName)}
            style={{ height: `${sizeEm}em`, width: 'auto' }}
            loading="lazy"
            decoding="async"
          />
        )
      }

      lastIndex = endIndex
    }

    if (lastIndex < text.length) {
      flushRun()
      out.push(text.slice(lastIndex))
    } else {
      flushRun()
    }

    return <span className={className}>{out}</span>
  }, [className, map, sizeEm, symbolClassName, text])

  return <>{nodes}</>
}

