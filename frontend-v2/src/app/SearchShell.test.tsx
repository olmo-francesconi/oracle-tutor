import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SearchShell } from './SearchShell'
import { buildClearedState, buildSearchFailureState, buildSearchLoadingState, buildSearchSuccessState } from './searchShellState'
import type { FilterState, SimilarCardsPage } from '../types/api'
import type { SearchShellState } from '../types/ui'

const { searchOracleTextMock, getOracleSamplesMock } = vi.hoisted(() => ({
  searchOracleTextMock: vi.fn<
    (query: string, offset: number, limit: number, filters?: FilterState, signal?: AbortSignal) => Promise<SimilarCardsPage>
  >(),
  getOracleSamplesMock: vi.fn(() => Promise.resolve({ texts: [], terms: [] })),
}))

const { reportErrorMock, trackMock } = vi.hoisted(() => ({
  reportErrorMock: vi.fn(),
  trackMock: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  getOracleSamples: getOracleSamplesMock,
  searchOracleText: searchOracleTextMock,
}))

vi.mock('../lib/observability', () => ({
  reportError: reportErrorMock,
  track: trackMock,
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
      <button type="button" onClick={() => onChange({ format: 'modern' })}>
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

const BASE_STATE: SearchShellState = {
  draftQuery: '',
  submittedQuery: null,
  filters: {},
  error: null,
  results: [],
  hasMore: false,
  isLoading: false,
  isLoadingMore: false,
}

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

describe('SearchShell state helpers', () => {
  it('builds loading, success, failure, and cleared states', () => {
    const loadingState = buildSearchLoadingState(BASE_STATE, 'bolt', { colors: 'R' })
    expect(loadingState).toMatchObject({
      submittedQuery: 'bolt',
      filters: { colors: 'R' },
      error: null,
      isLoading: true,
      results: [],
    })

    const successState = buildSearchSuccessState(BASE_STATE, 'bolt', { colors: 'R' }, createPage('Lightning Bolt'))
    expect(successState).toMatchObject({
      submittedQuery: 'bolt',
      filters: { colors: 'R' },
      isLoading: false,
      results: [{ name: 'Lightning Bolt' }],
    })

    const failureState = buildSearchFailureState(BASE_STATE, 'bolt', { colors: 'R' }, 'bad request')
    expect(failureState).toMatchObject({
      submittedQuery: 'bolt',
      filters: { colors: 'R' },
      error: 'bad request',
      isLoading: false,
    })

    const clearedState = buildClearedState({
      ...BASE_STATE,
      draftQuery: 'bolt',
      submittedQuery: 'bolt',
      filters: { colors: 'R' },
      error: 'bad request',
      results: createPage('Lightning Bolt').items,
      hasMore: true,
      isLoading: true,
      isLoadingMore: true,
    } as SearchShellState)

    expect(clearedState).toEqual(BASE_STATE)
  })
})

describe('SearchShell integration', () => {
  beforeEach(() => {
    searchOracleTextMock.mockReset()
    getOracleSamplesMock.mockClear()
    reportErrorMock.mockReset()
    trackMock.mockReset()
    window.history.replaceState({}, '', '/')
  })

  it('hydrates the initial query from the url and fetches results', async () => {
    window.history.replaceState({}, '', '/?q=burn')
    searchOracleTextMock.mockResolvedValue(createPage('Lightning Bolt'))

    render(<SearchShell />)

    await waitFor(() => {
      expect(searchOracleTextMock).toHaveBeenCalledWith('burn', 0, 24, {}, expect.any(AbortSignal))
    })

    expect(await screen.findByText('Lightning Bolt')).toBeInTheDocument()
  })

  it('submits a search and writes the query to the url', async () => {
    searchOracleTextMock.mockResolvedValue(createPage('Counterspell'))

    render(<SearchShell />)

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

    render(<SearchShell />)

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

    render(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))
    await screen.findByText('Card One')

    fireEvent.click(screen.getByText('apply modern filter'))

    await screen.findByText('Card Modern')

    expect(searchOracleTextMock).toHaveBeenNthCalledWith(
      2,
      'value',
      0,
      24,
      { format: 'modern' },
      expect.any(AbortSignal)
    )
    expect(window.location.search).toBe('?q=value&format=modern')
  })

  it('tracks clearing filters once and refetches without filters', async () => {
    searchOracleTextMock
      .mockResolvedValueOnce(createPage('Card One'))
      .mockResolvedValueOnce(createPage('Card Modern'))
      .mockResolvedValueOnce(createPage('Card Reset'))

    render(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))
    await screen.findByText('Card One')

    fireEvent.click(screen.getByText('apply modern filter'))
    await screen.findByText('Card Modern')

    fireEvent.click(screen.getByText('clear filters'))
    await screen.findByText('Card Reset')

    expect(trackMock).toHaveBeenCalledWith('filters_cleared', {
      previousKeys: ['format'],
    })
    expect(trackMock.mock.calls.filter(([eventName]) => eventName === 'filters_changed')).toHaveLength(1)
    expect(trackMock.mock.calls.filter(([eventName]) => eventName === 'filters_cleared')).toHaveLength(1)
    expect(searchOracleTextMock).toHaveBeenNthCalledWith(3, 'value', 0, 24, {}, expect.any(AbortSignal))
    expect(window.location.search).toBe('?q=value')
  })

  it('shows a global api-down overlay on home when bootstrap samples cannot load', async () => {
    getOracleSamplesMock.mockRejectedValueOnce(new Error('Failed to fetch'))

    render(<SearchShell />)

    expect(await screen.findByText('The catalog is off the wire.')).toBeInTheDocument()
    expect(screen.getByText('The front page cannot reach the catalog right now.')).toBeInTheDocument()
  })

  it('shows a global api-down overlay on results when the search request cannot reach the api', async () => {
    searchOracleTextMock.mockRejectedValueOnce(new Error('Failed to fetch'))

    render(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))

    expect(await screen.findByText('The catalog is off the wire.')).toBeInTheDocument()
    expect(screen.getByText('The results shell lost contact with the catalog.')).toBeInTheDocument()
    expect(screen.queryByText('Results did not land cleanly.')).not.toBeInTheDocument()
  })

  it('keeps non-network search failures as local search errors', async () => {
    searchOracleTextMock.mockRejectedValueOnce(new Error('Request failed: 422 - invalid query'))

    render(<SearchShell />)

    fireEvent.change(screen.getByLabelText('search input'), { target: { value: 'value' } })
    fireEvent.click(screen.getByText('submit search'))

    expect(await screen.findByText('Results did not land cleanly.')).toBeInTheDocument()
    expect(screen.queryByText('The catalog is off the wire.')).not.toBeInTheDocument()
  })
})
