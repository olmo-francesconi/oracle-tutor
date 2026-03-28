import {
  decodeCardTypeFilter,
  decodeFormatFilter,
  encodeCardTypeFilter,
  encodeFormatFilter,
  normalizeFilterState,
} from './filters'
import type { FilterState } from '../types/api'

const QUERY_PARAM = 'q'
const COLORS_PARAM = 'colors'
const CARD_TYPE_PARAM = 'type'
const FORMAT_PARAM = 'format'
const CMC_MIN_PARAM = 'cmcMin'
const CMC_MAX_PARAM = 'cmcMax'
const RARITIES_PARAM = 'rarity'
const MATCH_MODE_PARAM = 'match'
const COLOR_FEATURE_PARAM = 'colorBy'

type SearchUrlState = {
  query: string | null
  filters: FilterState
}

function readNumberParam(params: URLSearchParams, key: string): number | undefined {
  const rawValue = params.get(key)
  if (rawValue === null || rawValue === '') return undefined

  const nextValue = Number(rawValue)
  return Number.isFinite(nextValue) ? nextValue : undefined
}

export function readSearchStateFromUrl(): SearchUrlState {
  const params = new URLSearchParams(window.location.search)
  const query = params.get(QUERY_PARAM)?.trim() ?? ''
  const rarities = params.get(RARITIES_PARAM)?.split(',').filter(Boolean)

  const filters = normalizeFilterState({
    colors: params.get(COLORS_PARAM) || undefined,
    cardType: decodeCardTypeFilter(params.get(CARD_TYPE_PARAM) || undefined),
    format: decodeFormatFilter(params.get(FORMAT_PARAM) || undefined),
    cmcMin: readNumberParam(params, CMC_MIN_PARAM),
    cmcMax: readNumberParam(params, CMC_MAX_PARAM),
    rarities: rarities?.length ? rarities : undefined,
    matchMode: (params.get(MATCH_MODE_PARAM) as FilterState['matchMode']) || undefined,
    colorFeature: (params.get(COLOR_FEATURE_PARAM) as FilterState['colorFeature']) || undefined,
  })

  return {
    query: query || null,
    filters,
  }
}

export function writeSearchStateToUrl(query: string | null, filters: FilterState) {
  const url = new URL(window.location.href)
  const params = new URLSearchParams(url.search)
  const normalizedFilters = normalizeFilterState(filters)

  if (query) {
    params.set(QUERY_PARAM, query)
  } else {
    params.delete(QUERY_PARAM)
  }

  if (normalizedFilters.colors) params.set(COLORS_PARAM, normalizedFilters.colors)
  else params.delete(COLORS_PARAM)

  const encodedCardTypes = encodeCardTypeFilter(normalizedFilters.cardType)
  if (encodedCardTypes) params.set(CARD_TYPE_PARAM, encodedCardTypes)
  else params.delete(CARD_TYPE_PARAM)

  const encodedFormats = encodeFormatFilter(normalizedFilters.format)
  if (encodedFormats) params.set(FORMAT_PARAM, encodedFormats)
  else params.delete(FORMAT_PARAM)

  if (normalizedFilters.cmcMin !== undefined) params.set(CMC_MIN_PARAM, String(normalizedFilters.cmcMin))
  else params.delete(CMC_MIN_PARAM)

  if (normalizedFilters.cmcMax !== undefined) params.set(CMC_MAX_PARAM, String(normalizedFilters.cmcMax))
  else params.delete(CMC_MAX_PARAM)

  if (normalizedFilters.rarities?.length) params.set(RARITIES_PARAM, normalizedFilters.rarities.join(','))
  else params.delete(RARITIES_PARAM)

  if (normalizedFilters.matchMode) params.set(MATCH_MODE_PARAM, normalizedFilters.matchMode)
  else params.delete(MATCH_MODE_PARAM)

  if (normalizedFilters.colorFeature) params.set(COLOR_FEATURE_PARAM, normalizedFilters.colorFeature)
  else params.delete(COLOR_FEATURE_PARAM)

  const nextSearch = params.toString()
  const nextUrl = `${url.pathname}${nextSearch ? `?${nextSearch}` : ''}`
  window.history.pushState({ query, filters: normalizedFilters }, '', nextUrl)
}
