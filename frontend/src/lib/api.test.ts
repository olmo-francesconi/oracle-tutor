import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import {
  assertOk,
  buildSimilarCardsParams,
  getOracleSamples,
  normalizeCard,
  normalizeCardMatch,
  normalizeSimilarCard,
} from './api'

const anySchema = z.unknown()

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
    const schema = z.object({ ok: z.boolean() })
    const response = createJsonResponse({ ok: true }, { status: 200 })

    await expect(assertOk(response, schema)).resolves.toEqual({ ok: true })
  })

  it('includes string detail from json bodies', async () => {
    const response = createJsonResponse({ detail: 'bad request' }, { status: 400 })

    await expect(assertOk(response, anySchema)).rejects.toThrow('Request failed: 400 - bad request')
  })

  it('includes nested json detail payloads', async () => {
    const response = createJsonResponse({ detail: { field: 'q', error: 'required' } }, { status: 422 })

    await expect(assertOk(response, anySchema)).rejects.toThrow('Request failed: 422 - {"field":"q","error":"required"}')
  })

  it('falls back to response text for non-json bodies', async () => {
    const response = new Response('server exploded', { status: 500 })

    await expect(assertOk(response, anySchema)).rejects.toThrow('Request failed: 500 - server exploded')
  })

  it('rejects successful responses that do not match the schema', async () => {
    const schema = z.object({ ok: z.boolean() })
    const response = createJsonResponse({ ok: 'yes' }, { status: 200 })

    await expect(assertOk(response, schema)).rejects.toThrow(/Malformed response/)
  })
})

describe('getOracleSamples', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('surfaces oracle sample request failures to the shell', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ detail: 'unavailable' }, { status: 503 }))

    await expect(getOracleSamples()).rejects.toThrow('Request failed: 503 - unavailable')
  })
})

describe('filter param builder', () => {
  it('omits undefined filter values', () => {
    expect(buildSimilarCardsParams(24, 0, {})).toEqual({ limit: 24, offset: 0 })
  })

  it('serializes a full filter object', () => {
    expect(
      buildSimilarCardsParams(24, 48, {
        cardType: ['instant', 'sorcery'],
        colors: 'UR',
        format: ['modern', 'legacy'],
        cmcMin: 1,
        cmcMax: 3,
        rarities: ['rare', 'mythic'],
        matchMode: 'exact',
        colorFeature: 'colors',
      })
    ).toEqual({
      limit: 24,
      offset: 48,
      card_type: 'is',
      colors: 'UR',
      format: 'ml',
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
