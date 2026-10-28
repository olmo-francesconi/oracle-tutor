import {
  decodeCardTypeFilter,
  decodeFormatFilter,
  encodeCardTypeFilter,
  encodeFormatFilter,
  normalizeFilterState,
} from './filters'
import {
  buildAbilitySelection,
  decodeAbilityList,
  encodeAbilityList,
  excludedAbilities,
  includedAbilities,
} from './abilitySelection'
import type { FilterState } from '../types/api'
import type { AbilitySelection } from '../types/ui'

const QUERY_PARAM = 'q'
const CARD_PARAM = 'card'
const FACE_PARAM = 'face'
const INCLUDE_ABILITIES_PARAM = 'inc'
const EXCLUDE_ABILITIES_PARAM = 'exc'
const COLORS_PARAM = 'colors'
const CARD_TYPE_PARAM = 'type'
const FORMAT_PARAM = 'format'
const CMC_MIN_PARAM = 'cmcMin'
const CMC_MAX_PARAM = 'cmcMax'
const RARITIES_PARAM = 'rarity'
const MATCH_MODE_PARAM = 'match'
const COLOR_FEATURE_PARAM = 'colorBy'

type UrlPinnedCard = { oracle_id: string; face_ix: number; abilities?: AbilitySelection }

type SearchUrlState = {
  query: string | null
  pinnedCard: UrlPinnedCard | null
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
  })

  const abilities = cardId
    ? buildAbilitySelection(
        decodeAbilityList(params.get(INCLUDE_ABILITIES_PARAM)),
        decodeAbilityList(params.get(EXCLUDE_ABILITIES_PARAM))
      )
    : undefined

  return {
    query: query || null,
    pinnedCard: cardId ? { oracle_id: cardId, face_ix: faceIx, abilities } : null,
    filters,
  }
}

function buildCanonicalSearch(
  query: string | null,
  filters: FilterState,
  pinnedCard?: UrlPinnedCard | null
): { params: URLSearchParams; normalized: FilterState } {
  const normalized = normalizeFilterState(filters)
  // Build a fresh URLSearchParams in deterministic alphabetical key order so
  // the same logical state always serializes identically. Caller decides what
  // to do with prior unknown params: writeSearchStateToUrl drops them.
  const entries: Array<[string, string]> = []

  if (pinnedCard) {
    entries.push([CARD_PARAM, pinnedCard.oracle_id])
    if (pinnedCard.face_ix > 0) entries.push([FACE_PARAM, String(pinnedCard.face_ix)])
    const include = encodeAbilityList(includedAbilities(pinnedCard.abilities))
    if (include) entries.push([INCLUDE_ABILITIES_PARAM, include])
    const exclude = encodeAbilityList(excludedAbilities(pinnedCard.abilities))
    if (exclude) entries.push([EXCLUDE_ABILITIES_PARAM, exclude])
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
  pinnedCard?: UrlPinnedCard | null
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
  pinnedCard?: UrlPinnedCard | null
): string {
  const cleanOrigin = origin.replace(/\/+$/, '')
  // The canonical URL strips filters and ability selections: the same card or
  // text query with different tuning all canonicalizes to the untuned URL to
  // avoid duplicate-content fanout across permutations.
  const canonicalState = buildCanonicalSearch(
    query,
    {},
    pinnedCard ? { oracle_id: pinnedCard.oracle_id, face_ix: pinnedCard.face_ix } : pinnedCard
  )
  const search = canonicalState.params.toString()
  return `${cleanOrigin}/${search ? `?${search}` : ''}`
}
