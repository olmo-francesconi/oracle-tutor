import { cn } from '../lib/cn'
import { getManaClass, TOKEN_RE } from '../lib/manaSymbols'

export type SymbolTextProps = {
  text?: string | null
  className?: string
  symbolClassName?: string
  /** Unused — kept for API compatibility. */
  sizeEm?: number
}

export function SymbolText({ text, className, symbolClassName }: SymbolTextProps) {
  if (!text) return null

  const parts = text.split(TOKEN_RE.source ? /(\{[^}]*\})/g : /(\{[^}]*\})/g)

  return (
    <span className={cn('inline-flex flex-wrap items-baseline gap-0.5', className)}>
      {parts.map((part, i) => {
        if (part.startsWith('{') && part.endsWith('}')) {
          const cls = getManaClass(part)
          if (cls) {
            return (
              <i
                key={i}
                className={cn(cls, 'ms-cost', symbolClassName)}
                title={part}
                aria-label={part}
                style={{ fontSize: '0.9em', verticalAlign: 'middle', flexShrink: 0, overflow: 'visible' }}
              />
            )
          }
        }
        return <span key={i}>{part}</span>
      })}
    </span>
  )
}
