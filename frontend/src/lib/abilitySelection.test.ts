import { describe, expect, it } from 'vitest'
import {
  buildAbilitySelection,
  cycleAbilityChoice,
  decodeAbilityList,
  encodeAbilityList,
  excludedAbilities,
  includedAbilities,
  setAbilityChoices,
} from './abilitySelection'

describe('cycleAbilityChoice', () => {
  it('cycles untouched → forced → rejected → untouched', () => {
    const forced = cycleAbilityChoice({}, 1)
    expect(forced).toEqual({ 1: 'include' })

    const rejected = cycleAbilityChoice(forced, 1)
    expect(rejected).toEqual({ 1: 'exclude' })

    expect(cycleAbilityChoice(rejected, 1)).toEqual({})
  })

  it('leaves the other abilities alone', () => {
    expect(cycleAbilityChoice({ 0: 'exclude', 2: 'include' }, 2)).toEqual({
      0: 'exclude',
      2: 'exclude',
    })
  })
})

describe('setAbilityChoices', () => {
  it('applies one choice across a group', () => {
    expect(setAbilityChoices({ 3: 'include' }, [0, 1], 'exclude')).toEqual({
      0: 'exclude',
      1: 'exclude',
      3: 'include',
    })
  })

  it('clears only the targeted group', () => {
    expect(setAbilityChoices({ 0: 'exclude', 1: 'exclude', 3: 'include' }, [0, 1], null)).toEqual({
      3: 'include',
    })
  })

  it('overrides whatever the group was set to before', () => {
    expect(setAbilityChoices({ 0: 'include' }, [0], 'exclude')).toEqual({ 0: 'exclude' })
  })
})

describe('selection readers', () => {
  const selection = { 5: 'include', 0: 'exclude', 2: 'include' } as const

  it('splits and sorts by choice', () => {
    expect(includedAbilities(selection)).toEqual([2, 5])
    expect(excludedAbilities(selection)).toEqual([0])
  })

  it('treats an absent selection as empty', () => {
    expect(includedAbilities(undefined)).toEqual([])
    expect(excludedAbilities(undefined)).toEqual([])
  })
})

describe('url encoding', () => {
  it('round-trips a selection', () => {
    const selection = buildAbilitySelection(decodeAbilityList('2,0'), decodeAbilityList('1'))

    expect(selection).toEqual({ 0: 'include', 2: 'include', 1: 'exclude' })
    expect(encodeAbilityList(includedAbilities(selection))).toBe('0,2')
    expect(encodeAbilityList(excludedAbilities(selection))).toBe('1')
  })

  it('omits an empty list so untuned state has no param', () => {
    expect(encodeAbilityList([])).toBeUndefined()
    expect(buildAbilitySelection([], [])).toBeUndefined()
  })

  it('drops malformed and negative indices', () => {
    expect(decodeAbilityList('0,nope,-1,2.5,3')).toEqual([0, 3])
    expect(decodeAbilityList(null)).toEqual([])
  })

  it('deduplicates repeated indices', () => {
    expect(decodeAbilityList('2,2,1')).toEqual([1, 2])
  })

  it('lets forced win over rejected so a hand-edited url cannot send both', () => {
    expect(buildAbilitySelection([1], [1, 2])).toEqual({ 1: 'include', 2: 'exclude' })
  })
})
