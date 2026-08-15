import {
  decodeCardTypeFilter,
  decodeFormatFilter,
  encodeCardTypeFilter,
  encodeFormatFilter,
  normalizeFilterState,
} from './filters'
import type { FilterState } from '../types/api'

const QUERY_PARAM = 'q'
const CARD_PARAM = 'card'
const FACE_PARAM = 'face'
const COLORS_PARAM = 'colors'
const CARD_TYPE_PARAM = 'type'
const FORMAT_PARAM = 'format'
const CMC_MIN_PARAM = 'cmcMin'
const CMC_MAX_PARAM = 'cmcMax'
const RARITIES_PARAM = 'rarity'
const MATCH_MODE_PARAM = 'match'
const COLOR_FEATURE_PARAM = 'colorBy'
const IGNORE_KEYWORDS_PARAM = 'noKw'

type SearchUrlState = {
  query: string | null
  pinnedCard: { oracle_id: string; face_ix: number } | null
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
  const cardId = params.get(CARD_PARAM)?.trim() ?? ''
  const faceIx = cardId ? (readNumberParam(params, FACE_PARAM) ?? 0) : 0
  const rarities = params.get(RARITIES_PARAM)?.split(',').filter(Boolean)

  const filters = normalizeFilterState({
    colors: params.get(COLORS_PARAM) || undefined,
    cardType: decodeCardTypeFilter(params.get(CARD_TYPE_PARAM) || undefined),
    format: decodeFormatFilter(params.get(FORMAT_PARAM) || undefined),
    cmcMin: readNumberParam(params, CMC_MIN_PARAM),
    cmcMax: readNumberParam(params, CMC_MAX_PARAM),
    rarities: rarities?.length ? rarities : undefined,
    // Unvalidated casts — normalizeFilterState drops unknown values against its enum allowlists.
    matchMode: params.get(MATCH_MODE_PARAM) as FilterState['matchMode'],
    colorFeature: params.get(COLOR_FEATURE_PARAM) as FilterState['colorFeature'],
    ignoreKeywords: params.get(IGNORE_KEYWORDS_PARAM) === '1',
  })

  return {
    query: query || null,
    pinnedCard: cardId ? { oracle_id: cardId, face_ix: faceIx } : null,
    filters,
  }
}

function buildCanonicalSearch(
  query: string | null,
  filters: FilterState,
  pinnedCard?: { oracle_id: string; face_ix: number } | null
): { params: URLSearchParams; normalized: FilterState } {
  const normalized = normalizeFilterState(filters)
  // Build a fresh URLSearchParams in deterministic alphabetical key order so
  // the same logical state always serializes identically. Caller decides what
  // to do with prior unknown params: writeSearchStateToUrl drops them.
  const entries: Array<[string, string]> = []

  if (pinnedCard) {
    entries.push([CARD_PARAM, pinnedCard.oracle_id])
    if (pinnedCard.face_ix > 0) entries.push([FACE_PARAM, String(pinnedCard.face_ix)])
  } else if (query) {
    entries.push([QUERY_PARAM, query])
  }

  if (normalized.cmcMax !== undefined) entries.push([CMC_MAX_PARAM, String(normalized.cmcMax)])
  if (normalized.cmcMin !== undefined) entries.push([CMC_MIN_PARAM, String(normalized.cmcMin)])
  if (normalized.colorFeature) entries.push([COLOR_FEATURE_PARAM, normalized.colorFeature])
  if (normalized.colors) entries.push([COLORS_PARAM, normalized.colors])

  const encodedFormats = encodeFormatFilter(normalized.format)
  if (encodedFormats) entries.push([FORMAT_PARAM, encodedFormats])

  if (normalized.matchMode) entries.push([MATCH_MODE_PARAM, normalized.matchMode])
  if (normalized.ignoreKeywords) entries.push([IGNORE_KEYWORDS_PARAM, '1'])

  if (normalized.rarities?.length) {
    const sortedRarities = [...normalized.rarities].sort()
    entries.push([RARITIES_PARAM, sortedRarities.join(',')])
  }

  const encodedCardTypes = encodeCardTypeFilter(normalized.cardType)
  if (encodedCardTypes) entries.push([CARD_TYPE_PARAM, encodedCardTypes])

  entries.sort(([a], [b]) => a.localeCompare(b))

  const params = new URLSearchParams()
  for (const [key, value] of entries) params.append(key, value)
  return { params, normalized }
}

export function writeSearchStateToUrl(
  query: string | null,
  filters: FilterState,
  pinnedCard?: { oracle_id: string; face_ix: number } | null
) {
  const url = new URL(window.location.href)
  const { params, normalized } = buildCanonicalSearch(query, filters, pinnedCard)
  const nextSearch = params.toString()
  const nextUrl = `${url.pathname}${nextSearch ? `?${nextSearch}` : ''}`
  window.history.pushState({ query, filters: normalized }, '', nextUrl)
}

export function buildCanonicalUrl(
  origin: string,
  query: string | null,
  pinnedCard?: { oracle_id: string; face_ix: number } | null
): string {
  const cleanOrigin = origin.replace(/\/+$/, '')
  // The canonical URL strips filters: the same card or text query with
  // different filters all canonicalize to the unfiltered URL to avoid
  // duplicate-content fanout across filter permutations.
  const canonicalState = buildCanonicalSearch(query, {}, pinnedCard)
  const search = canonicalState.params.toString()
  return `${cleanOrigin}/${search ? `?${search}` : ''}`
}
