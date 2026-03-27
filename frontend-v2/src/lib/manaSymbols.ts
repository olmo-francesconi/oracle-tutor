const TOKEN_SPLIT_RE = /(\{[^}]*\})/g

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

export function getManaClass(symbol: string): string | null {
  const content = symbol.replace(/^\{|\}$/g, '').toLowerCase()
  if (SPECIAL[content]) return SPECIAL[content]

  const normalized = content.replace(/\//g, '')
  if (/^[a-z0-9]+$/.test(normalized)) return `ms ms-${normalized}`

  return null
}

export function splitSymbolParts(text: string): string[] {
  return text.split(TOKEN_SPLIT_RE).filter((part) => part.length > 0)
}
