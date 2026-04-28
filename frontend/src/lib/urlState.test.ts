import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { readSearchStateFromUrl, writeSearchStateToUrl } from './urlState'

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
