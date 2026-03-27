const TOKEN_SPLIT_RE = /(\{[^}]*\})/g
const SUPPORTED_SINGLE_SYMBOLS = ['w', 'u', 'b', 'r', 'g', 'c', 's', 'x', 'y', 'z', 't', 'q', 'e', 'a', 'p'] as const
const SUPPORTED_NAMED_SYMBOLS = ['paw', 'infinity', '1/2', 'acorn'] as const

const SPECIAL: Record<string, string> = {
  t: 'ms ms-tap',
  q: 'ms ms-untap',
  a: 'ms ms-acorn',
  paw: 'ms ms-paw',
  s: 'ms ms-s',
  c: 'ms ms-c',
  e: 'ms ms-e',
  infinity: 'ms ms-infinity',
  '1/2': 'ms ms-half',
  acorn: 'ms ms-acorn',
}

function isSupportedHybridContent(content: string): boolean {
  const parts = content.split('/')
  if (parts.length < 2 || parts.length > 3) return false

  return parts.every((part) => {
    if (part === 'p') return true
    if (part === '2') return true
    return SUPPORTED_SINGLE_SYMBOLS.includes(part as (typeof SUPPORTED_SINGLE_SYMBOLS)[number])
  })
}

export function isSupportedManaSymbol(symbol: string): boolean {
  if (!symbol.startsWith('{') || !symbol.endsWith('}')) return false

  const content = symbol.slice(1, -1).toLowerCase()
  if (!content) return false
  if (SUPPORTED_SINGLE_SYMBOLS.includes(content as (typeof SUPPORTED_SINGLE_SYMBOLS)[number])) return true
  if (SUPPORTED_NAMED_SYMBOLS.includes(content as (typeof SUPPORTED_NAMED_SYMBOLS)[number])) return true
  if (/^\d{1,2}$/.test(content)) return true
  if (content.includes('/')) return isSupportedHybridContent(content)

  return false
}

export function getManaClass(symbol: string): string | null {
  if (!isSupportedManaSymbol(symbol)) return null

  const content = symbol.replace(/^\{|\}$/g, '').toLowerCase()
  if (SPECIAL[content]) return SPECIAL[content]

  const normalized = content.replace(/\//g, '')
  if (/^[a-z0-9]+$/.test(normalized)) return `ms ms-${normalized}`

  return null
}

export function splitSymbolParts(text: string): string[] {
  return text.split(TOKEN_SPLIT_RE).filter((part) => part.length > 0)
}
