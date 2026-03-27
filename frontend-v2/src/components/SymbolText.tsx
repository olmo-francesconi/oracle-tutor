import { getManaClass, splitSymbolParts } from '../lib/manaSymbols'

interface SymbolTextProps {
  text: string
}

export function SymbolText({ text }: SymbolTextProps) {
  return (
    <>
      {splitSymbolParts(text).map((part, index) => {
        if (part.startsWith('{') && part.endsWith('}')) {
          const manaClass = getManaClass(part)

          if (manaClass) {
            return (
              <span key={`${part}-${index}`} className="symbol-token" aria-label={part}>
                <i className={`${manaClass} symbol-token-icon`} aria-hidden="true" />
              </span>
            )
          }
        }

        return <span key={`${part}-${index}`}>{part}</span>
      })}
    </>
  )
}
