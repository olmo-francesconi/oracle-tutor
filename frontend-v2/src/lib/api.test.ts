import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  assertOk,
  buildSimilarCardsParams,
  clearCardSearchCache,
  normalizeCard,
  normalizeCardMatch,
  normalizeSimilarCard,
  searchCards,
} from './api'

function createJsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    headers: {
      'Content-Type': 'application/json',
    },
    ...init,
  })
}

describe('assertOk', () => {
  it('returns parsed json for successful responses', async () => {
    const response = createJsonResponse({ ok: true }, { status: 200 })

    await expect(assertOk<{ ok: boolean }>(response)).resolves.toEqual({ ok: true })
  })

  it('includes string detail from json bodies', async () => {
    const response = createJsonResponse({ detail: 'bad request' }, { status: 400 })

    await expect(assertOk(response)).rejects.toThrow('Request failed: 400 - bad request')
  })

  it('includes nested json detail payloads', async () => {
    const response = createJsonResponse({ detail: { field: 'q', error: 'required' } }, { status: 422 })

    await expect(assertOk(response)).rejects.toThrow('Request failed: 422 - {"field":"q","error":"required"}')
  })

  it('falls back to response text for non-json bodies', async () => {
    const response = new Response('server exploded', { status: 500 })

    await expect(assertOk(response)).rejects.toThrow('Request failed: 500 - server exploded')
  })
})

describe('searchCards cache', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    clearCardSearchCache()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
    clearCardSearchCache()
  })

  it('returns cached results without refetching', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse([
        {
          name: 'Lightning Bolt',
          oracle_id: 'oracle-1',
          scryfall_id: 'card-1',
          face_ix: 0,
          image_side: 'front',
        },
      ])
    )

    const first = await searchCards('bolt', 6, 0)
    const second = await searchCards('bolt', 6, 0)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(first).toEqual(second)
    expect(first[0]?.id).toBe('card-1')
  })

  it('evicts the oldest cache entry when the limit is exceeded', async () => {
    fetchMock.mockImplementation((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const query = new URL(url, 'http://localhost').searchParams.get('q')

      return Promise.resolve(
        createJsonResponse([
          {
            name: query,
            oracle_id: `oracle-${query}`,
            scryfall_id: `card-${query}`,
            face_ix: 0,
            image_side: 'front',
          },
        ])
      )
    })

    for (let index = 0; index <= 40; index += 1) {
      await searchCards(`query-${index}`, 6, 0)
    }

    await searchCards('query-0', 6, 0)

    expect(fetchMock).toHaveBeenCalledTimes(42)
  })
})

describe('filter param builder', () => {
  it('omits undefined filter values', () => {
    expect(buildSimilarCardsParams(24, 0, {})).toEqual({ limit: 24, offset: 0 })
  })

  it('serializes a full filter object', () => {
    expect(
      buildSimilarCardsParams(24, 48, {
        cardType: 'instant',
        colors: 'UR',
        format: 'modern',
        cmcMin: 1,
        cmcMax: 3,
        rarities: ['rare', 'mythic'],
        matchMode: 'exact',
        colorFeature: 'colors',
      })
    ).toEqual({
      limit: 24,
      offset: 48,
      card_type: 'instant',
      colors: 'UR',
      format: 'modern',
      cmc_min: 1,
      cmc_max: 3,
      rarity: 'rm',
      match_mode: 'exact',
      color_feature: 'colors',
    })
  })
})

describe('normalizers', () => {
  it('fills card ids from scryfall ids', () => {
    expect(
      normalizeCardMatch({
        name: 'Counterspell',
        oracle_id: 'oracle-2',
        scryfall_id: 'card-2',
        face_ix: 0,
        image_side: 'front',
      })
    ).toMatchObject({
      id: 'card-2',
      name: 'Counterspell',
    })
  })

  it('falls back to the primary face for missing card fields', () => {
    expect(
      normalizeCard({
        oracle_id: 'oracle-3',
        scryfall_id: 'card-3',
        name: 'Fire // Ice',
        faces: [
          {
            oracle_id: 'oracle-3',
            face_ix: 0,
            name: 'Fire',
            mana_cost: '{1}{R}',
            type_line: 'Instant',
            oracle_text: 'Fire text',
            colors: ['R'],
          },
        ],
      })
    ).toMatchObject({
      id: 'card-3',
      mana_cost: '{1}{R}',
      type_line: 'Instant',
      oracle_text: 'Fire text',
      colors: ['R'],
    })
  })

  it('normalizes similar cards the same way', () => {
    expect(
      normalizeSimilarCard({
        oracle_id: 'oracle-4',
        scryfall_id: 'card-4',
        name: 'Mystery Card',
        face_ix: 0,
        image_side: 'front',
        similarity: 0.92,
        faces: [
          {
            oracle_id: 'oracle-4',
            face_ix: 0,
            name: 'Mystery Card',
            oracle_text: 'Mystery text',
          },
        ],
      })
    ).toMatchObject({
      id: 'card-4',
      oracle_text: 'Mystery text',
      similarity: 0.92,
    })
  })
})
