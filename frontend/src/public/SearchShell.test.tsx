import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SearchShell } from './SearchShell'
import { renderWithQueryClient } from '../lib/testQueryClient'
import type { Card, FilterState, SimilarCardsPage } from '../types/api'

const { searchOracleTextMock, getOracleSamplesMock, getSimilarCardsMock, getCardMock } = vi.hoisted(() => ({
  searchOracleTextMock: vi.fn<
    (query: string, offset: number, limit: number, filters?: FilterState, signal?: AbortSignal) => Promise<SimilarCardsPage>
  >(),
  getOracleSamplesMock: vi.fn(() => Promise.resolve({ texts: [], terms: [] })),
  getSimilarCardsMock: vi.fn<
    (oracleId: string, faceIx: number, offset: number, limit: number, filters?: FilterState, signal?: AbortSignal) => Promise<SimilarCardsPage>
  >(),
  getCardMock: vi.fn<(id: string, signal?: AbortSignal) => Promise<Card>>(),
}))

vi.mock('../lib/api', () => ({
  getOracleSamples: getOracleSamplesMock,
  searchOracleText: searchOracleTextMock,
  getSimilarCards: getSimilarCardsMock,
  getCard: getCardMock,
}))

vi.mock('../components/background/DenseTextBackground', () => ({
  DenseTextBackground: () => null,
}))

vi.mock('../components/background/HomeEditorialText', () => ({
  HomeEditorialText: () => null,
}))

vi.mock('../components/SearchBox/SearchBox', () => ({
  SearchBox: ({
    value,
    onChange,
    onSubmit,
  }: {
    value: string
    onChange: (value: string) => void
    onSubmit: (submittedValue?: string) => void
  }) => (
    <div>
      <input
        aria-label="search input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <button type="button" onClick={() => onSubmit()}>
        submit search
      </button>
    </div>
  ),
}))

vi.mock('../components/FilterBar', () => ({
  FilterBar: ({
    onChange,
    onClear,
  }: {
    onChange: (filters: FilterState) => void
    onClear: () => void
  }) => (
    <div>
      <button type="button" onClick={() => onChange({ format: ['modern'] })}>
        apply modern filter
      </button>
      <button type="button" onClick={onClear}>
        clear filters
      </button>
    </div>
  ),
}))

vi.mock('../components/ResultsGrid', () => ({
  ResultsGrid: ({
    cards,
    hasMore,
    onLoadMore,
  }: {
    cards: Array<{ name: string }>
    hasMore: boolean
    onLoadMore: () => void
  }) => (
    <div>
      {cards.map((card) => (
        <div key={card.name}>{card.name}</div>
      ))}
      {hasMore ? (
        <button type="button" onClick={onLoadMore}>
          load more
        </button>
      ) : null}
    </div>
  ),
}))

function createPage(name: string, hasMore: boolean = false): SimilarCardsPage {
  return {
    items: [
      {
        id: `id-${name}`,
        oracle_id: `oracle-${name}`,
        scryfall_id: `scryfall-${name}`,
        name,
        face_ix: 0,
        image_side: 'front',
        similarity: 0.9,
      },
    ],
    has_more: hasMore,
  }
}

describe('SearchShell integration', () => {
  beforeEach(() => {
    searchOracleTextMock.mockReset()
    getSimilarCardsMock.mockReset()
    getCardMock.mockReset()
    getOracleSamplesMock.mockClear()
    window.history.replaceState({}, '', '/')
  })

  it('hydrates the initial query from the url and fetches results', async () => {
    window.history.replaceState({}, '', '/?q=burn')
    searchOracleTextMock.mockResolvedValue(createPage('Lightning Bolt'))

    renderWithQueryClient(<SearchShell />)

    await waitFor(() => {
      expect(searchOracleTextMock).toHaveBeenCalledWith('burn', 0, 24, {}, expect.any(AbortSignal))
    })

    expect(await screen.findByText('Lightning Bolt')).toBeInTheDocument()
  })

  it('submits a search and writes the query to the url', async () => {
    searchOracleTextMock.mockResolvedValue(createPage('Counterspell'))

    renderWithQueryClient(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'counter' } })
    fireEvent.click(screen.getByText('submit search'))

    await screen.findByText('Counterspell')

    expect(searchOracleTextMock).toHaveBeenCalledWith('counter', 0, 24, {}, expect.any(AbortSignal))
    expect(window.location.search).toBe('?q=counter')
  })

  it('loads more results using the current offset', async () => {
    searchOracleTextMock
      .mockResolvedValueOnce({
        items: [
          {
            id: 'id-1',
            oracle_id: 'oracle-1',
            scryfall_id: 'scryfall-1',
            name: 'Card One',
            face_ix: 0,
            image_side: 'front',
            similarity: 0.9,
          },
          {
            id: 'id-2',
            oracle_id: 'oracle-2',
            scryfall_id: 'scryfall-2',
            name: 'Card Two',
            face_ix: 0,
            image_side: 'front',
            similarity: 0.8,
          },
        ],
        has_more: true,
      })
      .mockResolvedValueOnce(createPage('Card Three'))

    renderWithQueryClient(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))
    await screen.findByText('Card One')

    fireEvent.click(screen.getByText('load more'))

    await screen.findByText('Card Three')

    expect(searchOracleTextMock).toHaveBeenNthCalledWith(2, 'value', 2, 24, {}, expect.any(AbortSignal))
  })

  it('restarts the search from page 0 when filters change', async () => {
    searchOracleTextMock
      .mockResolvedValueOnce(createPage('Card One'))
      .mockResolvedValueOnce(createPage('Card Modern'))

    renderWithQueryClient(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))
    await screen.findByText('Card One')

    fireEvent.click(screen.getByLabelText('Toggle filters'))
    fireEvent.click(screen.getByText('apply modern filter'))

    await screen.findByText('Card Modern')

    expect(searchOracleTextMock).toHaveBeenNthCalledWith(
      2,
      'value',
      0,
      24,
      { format: ['modern'] },
      expect.any(AbortSignal)
    )
    expect(window.location.search).toBe('?format=m&q=value')
  })

  it('clears filters and refetches without filters', async () => {
    searchOracleTextMock
      .mockResolvedValueOnce(createPage('Card One'))
      .mockResolvedValueOnce(createPage('Card Modern'))
      .mockResolvedValueOnce(createPage('Card Reset'))

    renderWithQueryClient(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))
    await screen.findByText('Card One')

    fireEvent.click(screen.getByLabelText('Toggle filters'))
    fireEvent.click(screen.getByText('apply modern filter'))
    await screen.findByText('Card Modern')

    fireEvent.click(screen.getByText('clear filters'))
    await screen.findByText('Card Reset')

    expect(searchOracleTextMock).toHaveBeenNthCalledWith(3, 'value', 0, 24, {}, expect.any(AbortSignal))
    expect(window.location.search).toBe('?q=value')
  })

  it('shows a global api-down overlay on home when bootstrap samples cannot load', async () => {
    getOracleSamplesMock.mockRejectedValueOnce(new Error('Failed to fetch'))
    vi.useFakeTimers()
    try {
      renderWithQueryClient(<SearchShell />)
      // SearchShell waits API_DOWN_OVERLAY_DELAY_MS (30s) of continuous
      // failure before hijacking the page with the offline overlay.
      await vi.advanceTimersByTimeAsync(30_000)
    } finally {
      vi.useRealTimers()
    }

    expect(await screen.findByText('Oracle Tutor offline.')).toBeInTheDocument()
    expect(
      screen.getByText('Oracle Tutor cannot reach the live catalog right now. Give it a second, then retry the connection.')
    ).toBeInTheDocument()
  })

  it('shows a global api-down overlay on results when the search request cannot reach the api', async () => {
    searchOracleTextMock.mockRejectedValueOnce(new Error('Failed to fetch'))
    vi.useFakeTimers()
    try {
      renderWithQueryClient(<SearchShell />)

      fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
      fireEvent.click(screen.getByText('submit search'))

      await vi.advanceTimersByTimeAsync(30_000)
    } finally {
      vi.useRealTimers()
    }

    expect(await screen.findByText('Oracle Tutor offline.')).toBeInTheDocument()
    expect(
      screen.getByText('Oracle Tutor cannot reach the live catalog right now. Give it a second, then retry the connection.')
    ).toBeInTheDocument()
    expect(screen.queryByText('Results unavailable.')).not.toBeInTheDocument()
  })

  it('keeps non-network search failures as local search errors', async () => {
    searchOracleTextMock.mockRejectedValueOnce(new Error('Request failed: 422 - invalid query'))

    renderWithQueryClient(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))

    expect(await screen.findByText('Results unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('Oracle Tutor offline.')).not.toBeInTheDocument()
  })
})
