import type { AbilityChoice, AbilitySelection } from '../types/ui'

const CYCLE: Record<AbilityChoice | 'none', AbilityChoice | 'none'> = {
  none: 'include',
  include: 'exclude',
  exclude: 'none',
}

/** Advance one ability through untouched → wanted → unwanted → untouched. */
export function cycleAbilityChoice(
  selection: AbilitySelection,
  abilityIx: number
): AbilitySelection {
  const next = CYCLE[selection[abilityIx] ?? 'none']
  const rest = Object.fromEntries(
    Object.entries(selection).filter(([key]) => Number(key) !== abilityIx)
  ) as AbilitySelection
  return next === 'none' ? rest : { ...rest, [abilityIx]: next }
}

/** Bulk-set a group of abilities to one choice, or clear them with `null`. */
export function setAbilityChoices(
  selection: AbilitySelection,
  indices: number[],
  choice: AbilityChoice | null
): AbilitySelection {
  const targeted = new Set(indices)
  const next = Object.fromEntries(
    Object.entries(selection).filter(([key]) => !targeted.has(Number(key)))
  ) as AbilitySelection
  if (choice !== null) for (const ix of indices) next[ix] = choice
  return next
}

function indicesOf(selection: AbilitySelection | undefined, choice: AbilityChoice): number[] {
  if (!selection) return []
  return Object.entries(selection)
    .filter(([, value]) => value === choice)
    .map(([key]) => Number(key))
    .sort((a, b) => a - b)
}

export function includedAbilities(selection: AbilitySelection | undefined): number[] {
  return indicesOf(selection, 'include')
}

export function excludedAbilities(selection: AbilitySelection | undefined): number[] {
  return indicesOf(selection, 'exclude')
}

export function encodeAbilityList(indices: number[]): string | undefined {
  return indices.length ? indices.join(',') : undefined
}

export function decodeAbilityList(raw: string | null): number[] {
  if (!raw) return []
  const seen = new Set<number>()
  for (const part of raw.split(',')) {
    const value = Number(part)
    if (Number.isInteger(value) && value >= 0) seen.add(value)
  }
  return [...seen].sort((a, b) => a - b)
}

export function buildAbilitySelection(
  include: number[],
  exclude: number[]
): AbilitySelection | undefined {
  const selection: AbilitySelection = {}
  for (const ix of include) selection[ix] = 'include'
  // Include wins on collision so a malformed URL can never send an ability as both.
  for (const ix of exclude) if (selection[ix] === undefined) selection[ix] = 'exclude'
  return Object.keys(selection).length ? selection : undefined
}
