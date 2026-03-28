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
      '/?q=bolt&colors=UR&type=instant&format=modern&cmcMin=1&cmcMax=3&rarity=rare,mythic&match=exact&colorBy=colors'
    )

    expect(readSearchStateFromUrl()).toEqual({
      query: 'bolt',
      filters: {
        colors: 'UR',
        cardType: 'instant',
        format: 'modern',
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
      filters: {
        cmcMax: 4,
      },
    })
  })

  it('writes query and filters into the url', () => {
    writeSearchStateToUrl('burn', {
      colors: 'R',
      cardType: 'sorcery',
      cmcMin: 1,
      rarities: ['common'],
    })

    expect(window.location.search).toBe('?q=burn&colors=R&type=sorcery&cmcMin=1&rarity=common')
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
