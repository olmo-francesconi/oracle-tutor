import { describe, expect, it } from 'vitest'
import { getManaClass, isSupportedManaSymbol } from './manaSymbols'

describe('manaSymbols', () => {
  it('supports numeric icons only up to the font limit', () => {
    expect(isSupportedManaSymbol('{20}')).toBe(true)
    expect(getManaClass('{20}')).toBe('ms ms-20')
    expect(isSupportedManaSymbol('{100}')).toBe(true)
    expect(getManaClass('{100}')).toBe('ms ms-100')
    expect(isSupportedManaSymbol('{21}')).toBe(false)
    expect(getManaClass('{21}')).toBeNull()
  })

  it('supports slash-separated and compact hybrid forms', () => {
    expect(isSupportedManaSymbol('{W/B}')).toBe(true)
    expect(getManaClass('{W/B}')).toBe('ms ms-wb')
    expect(isSupportedManaSymbol('{WB}')).toBe(true)
    expect(getManaClass('{WB}')).toBe('ms ms-wb')
  })

  it('supports compact phyrexian forms', () => {
    expect(isSupportedManaSymbol('{W/B/P}')).toBe(true)
    expect(getManaClass('{W/B/P}')).toBe('ms ms-wbp')
    expect(isSupportedManaSymbol('{WBP}')).toBe(true)
    expect(getManaClass('{WBP}')).toBe('ms ms-wbp')
  })
})
