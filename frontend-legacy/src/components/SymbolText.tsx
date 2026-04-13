import { cn } from '../lib/cn'
import { getManaClass, splitSymbolParts } from '../lib/manaSymbols'

export type SymbolTextProps = {
  text?: string | null
  className?: string
  symbolClassName?: string
  preserveLineBreaks?: boolean
  /** Unused — kept for API compatibility. */
  sizeEm?: number
}

export function SymbolText({ text, className, symbolClassName, preserveLineBreaks = false }: SymbolTextProps) {
  if (!text) return null

  const parts = splitSymbolParts(text)

  return (
    <span className={cn('inline-flex flex-wrap items-baseline gap-0.5', preserveLineBreaks && 'whitespace-pre-line', className)}>
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
        return <span key={i} className={cn(preserveLineBreaks && 'whitespace-pre-line')}>{part}</span>
      })}
    </span>
  )
}
