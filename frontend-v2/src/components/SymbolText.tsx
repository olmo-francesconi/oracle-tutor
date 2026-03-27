import { getManaClass, splitSymbolParts } from '../lib/manaSymbols'

interface SymbolTextProps {
  text: string
}

export function SymbolText({ text }: SymbolTextProps) {
  return (
    <>
      {splitSymbolParts(text).map((part, index) => {
        const key = `part-${index}`

        if (part.startsWith('{') && part.endsWith('}')) {
          const manaClass = getManaClass(part)

          if (manaClass) {
            return (
              <span key={key} className="inline-flex items-center align-middle" aria-label={part}>
                <i className={`${manaClass} ms-cost inline-block align-middle leading-none`} aria-hidden="true" />
              </span>
            )
          }
        }

        return <span key={key}>{part}</span>
      })}
    </>
  )
}
