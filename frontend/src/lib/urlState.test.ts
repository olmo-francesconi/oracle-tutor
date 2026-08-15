import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { buildCanonicalUrl, readSearchStateFromUrl, writeSearchStateToUrl } from './urlState'

describe('urlState', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
  })

  afterEach(() => {
    window.history.replaceState({}, '', '/')
  })

  it('reads query and filters from the url', () => {
    window.history.replaceState(
      {},
      '',
      '/?q=bolt&colors=UR&type=is&format=ml&cmcMin=1&cmcMax=3&rarity=rare,mythic&match=exact&colorBy=colors'
    )

    expect(readSearchStateFromUrl()).toEqual({
      query: 'bolt',
      pinnedCard: null,
      filters: {
        colors: 'UR',
        cardType: ['instant', 'sorcery'],
        format: ['modern', 'legacy'],
        cmcMin: 1,
        cmcMax: 3,
        rarities: ['rare', 'mythic'],
        matchMode: 'exact',
        colorFeature: 'colors',
      },
    })
  })

  it('ignores malformed numeric params', () => {
    window.history.replaceState({}, '', '/?q=test&cmcMin=nope&cmcMax=4')

    expect(readSearchStateFromUrl()).toEqual({
      query: 'test',
      pinnedCard: null,
      filters: {
        cmcMax: 4,
      },
    })
  })

  it('writes query and filters into the url', () => {
    writeSearchStateToUrl('burn', {
      colors: 'R',
      cardType: ['sorcery', 'instant'],
      cmcMin: 1,
      rarities: ['common'],
    })

    expect(window.location.search).toBe('?cmcMin=1&colors=R&q=burn&rarity=common&type=si')
  })

  it('reads an ability selection alongside the pinned card', () => {
    window.history.replaceState({}, '', '/?card=o1&face=1&inc=2,0&exc=1')

    expect(readSearchStateFromUrl()).toEqual({
      query: null,
      pinnedCard: {
        oracle_id: 'o1',
        face_ix: 1,
        abilities: { 0: 'include', 2: 'include', 1: 'exclude' },
      },
      filters: {},
    })
  })

  it('leaves abilities undefined when nothing is tuned', () => {
    window.history.replaceState({}, '', '/?card=o1')

    expect(readSearchStateFromUrl().pinnedCard).toEqual({
      oracle_id: 'o1',
      face_ix: 0,
      abilities: undefined,
    })
  })

  it('ignores an ability selection when there is no pinned card', () => {
    window.history.replaceState({}, '', '/?q=bolt&inc=0')

    expect(readSearchStateFromUrl().pinnedCard).toBeNull()
  })

  it('writes the ability selection into the url', () => {
    writeSearchStateToUrl(null, {}, {
      oracle_id: 'o1',
      face_ix: 0,
      abilities: { 2: 'include', 0: 'include', 1: 'exclude' },
    })

    expect(window.location.search).toBe('?card=o1&exc=1&inc=0%2C2')
  })

  it('strips the ability selection from the canonical url', () => {
    const canonical = buildCanonicalUrl('https://oracletutor.org', null, {
      oracle_id: 'o1',
      face_ix: 0,
      abilities: { 0: 'include', 1: 'exclude' },
    })

    expect(canonical).toBe('https://oracletutor.org/?card=o1')
  })

  it('removes cleared query and default filters from the url', () => {
    window.history.replaceState(
      {},
      '',
      '/?q=burn&colors=R&match=at_least&colorBy=identity'
    )

    writeSearchStateToUrl(null, {})

    expect(window.location.search).toBe('')
  })
})
