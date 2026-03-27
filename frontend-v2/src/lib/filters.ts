import type { FilterState } from '../types/api'

export const COLOR_OPTIONS = [
  { value: 'W', label: 'White', textOnSelected: '#111111', paleBg: '#f5edd8', bg: '#c8a96e', border: '#c8a96e' },
  { value: 'U', label: 'Blue', textOnSelected: '#ffffff', paleBg: '#d0ddef', bg: '#1e5094', border: '#1e5094' },
  { value: 'B', label: 'Black', textOnSelected: '#ffffff', paleBg: '#cecac6', bg: '#111111', border: '#111111' },
  { value: 'R', label: 'Red', textOnSelected: '#ffffff', paleBg: '#f5d0cb', bg: '#cc1100', border: '#cc1100' },
  { value: 'G', label: 'Green', textOnSelected: '#ffffff', paleBg: '#c8dacc', bg: '#2e6840', border: '#2e6840' },
  { value: 'C', label: 'Colorless', textOnSelected: '#ffffff', paleBg: '#e4e0db', bg: '#7a7670', border: '#7a7670' },
] as const

export const RARITY_OPTIONS = [
  { value: 'common', label: 'Common', short: 'C', textOnSelected: '#f0ede6', paleBg: '#cecac6', bg: '#333333', border: '#333333' },
  { value: 'uncommon', label: 'Uncommon', short: 'U', textOnSelected: '#ffffff', paleBg: '#dde4e9', bg: '#8499a8', border: '#7a8c9a' },
  { value: 'rare', label: 'Rare', short: 'R', textOnSelected: '#111111', paleBg: '#f5edd8', bg: '#c8a96e', border: '#b89050' },
  { value: 'mythic', label: 'Mythic', short: 'M', textOnSelected: '#ffffff', paleBg: '#f8dbc8', bg: '#c96428', border: '#b05420' },
] as const

export const FORMAT_OPTIONS = [
  'standard',
  'pioneer',
  'modern',
  'legacy',
  'vintage',
  'commander',
  'pauper',
] as const

export const CARD_TYPE_OPTIONS = [
  'creature',
  'instant',
  'sorcery',
  'enchantment',
  'artifact',
  'planeswalker',
  'land',
] as const

const MATCH_MODE_OPTIONS: NonNullable<FilterState['matchMode']>[] = ['at_least', 'at_most', 'exact']
const COLOR_FEATURE_OPTIONS: NonNullable<FilterState['colorFeature']>[] = ['identity', 'colors']

export function normalizeFilterState(filters: FilterState): FilterState {
  const next: FilterState = {}

  if (filters.cardType) next.cardType = filters.cardType
  if (filters.colors) next.colors = filters.colors
  if (filters.format) next.format = filters.format
  if (filters.cmcMin !== undefined && Number.isFinite(filters.cmcMin)) next.cmcMin = filters.cmcMin
  if (filters.cmcMax !== undefined && Number.isFinite(filters.cmcMax)) next.cmcMax = filters.cmcMax
  if (filters.rarities?.length) next.rarities = [...new Set(filters.rarities)]
  if (filters.matchMode && filters.matchMode !== 'at_least') next.matchMode = filters.matchMode
  if (filters.colorFeature && filters.colorFeature !== 'identity') next.colorFeature = filters.colorFeature

  return next
}

export function hasActiveFilters(filters: FilterState): boolean {
  return getActiveFilterCount(filters) > 0
}

export function getActiveFilterCount(filters: FilterState): number {
  let count = 0

  if (filters.cardType) count += 1
  if (filters.colors) count += 1
  if (filters.format) count += 1
  if (filters.cmcMin !== undefined || filters.cmcMax !== undefined) count += 1
  if (filters.rarities?.length) count += 1
  if (filters.matchMode && filters.matchMode !== 'at_least') count += 1
  if (filters.colorFeature && filters.colorFeature !== 'identity') count += 1

  return count
}

export function toggleFilterColor(filters: FilterState, color: string): FilterState {
  const current = filters.colors ? filters.colors.split('') : []
  const isSelected = current.includes(color)
  let nextColors = [...current]

  if (color === 'C') {
    nextColors = isSelected ? [] : ['C']
  } else {
    if (nextColors.includes('C')) {
      nextColors = nextColors.filter((value) => value !== 'C')
    }

    nextColors = isSelected
      ? nextColors.filter((value) => value !== color)
      : [...nextColors, color]
  }

  return normalizeFilterState({
    ...filters,
    colors: nextColors.join('') || undefined,
  })
}

export function toggleFilterRarity(filters: FilterState, rarity: string): FilterState {
  const current = filters.rarities ?? []
  const nextRarities = current.includes(rarity)
    ? current.filter((value) => value !== rarity)
    : [...current, rarity]

  return normalizeFilterState({
    ...filters,
    rarities: nextRarities.length > 0 ? nextRarities : undefined,
  })
}

export function cycleMatchMode(filters: FilterState): FilterState {
  const current = filters.matchMode ?? 'at_least'
  const currentIndex = MATCH_MODE_OPTIONS.indexOf(current)
  const nextMatchMode = MATCH_MODE_OPTIONS[(currentIndex + 1) % MATCH_MODE_OPTIONS.length]

  return normalizeFilterState({
    ...filters,
    matchMode: nextMatchMode,
  })
}

export function cycleColorFeature(filters: FilterState): FilterState {
  const current = filters.colorFeature ?? 'identity'
  const currentIndex = COLOR_FEATURE_OPTIONS.indexOf(current)
  const nextColorFeature = COLOR_FEATURE_OPTIONS[(currentIndex + 1) % COLOR_FEATURE_OPTIONS.length]

  return normalizeFilterState({
    ...filters,
    colorFeature: nextColorFeature,
  })
}
