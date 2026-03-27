const GENERIC_MANA_SYMBOLS = Array.from({ length: 11 }, (_, index) => `{${index}}`)
const COLORED_MANA_SYMBOLS = ['{W}', '{U}', '{B}', '{R}', '{G}', '{C}', '{S}']
const EXTRA_SYMBOLS = ['{T}', '{Q}', '{X}', '{Y}', '{Z}', '{E}', '{P}', '{TK}', '{PAW}']
const HYBRID_SYMBOLS = ['{W/U}', '{U/B}', '{B/R}', '{R/G}', '{G/W}']

const SYMBOLS = [
  ...EXTRA_SYMBOLS,
  ...COLORED_MANA_SYMBOLS,
  ...HYBRID_SYMBOLS,
  ...GENERIC_MANA_SYMBOLS,
]

interface ManaSymbolRailProps {
  onInsert: (symbol: string) => void
}

export function ManaSymbolRail({ onInsert }: ManaSymbolRailProps) {
  return (
    <div className="mana-rail" aria-label="Mana symbols">
      {SYMBOLS.map((symbol) => (
        <button
          key={symbol}
          type="button"
          className="mana-rail-button"
          onClick={() => onInsert(symbol)}
        >
          {symbol}
        </button>
      ))}
    </div>
  )
}
