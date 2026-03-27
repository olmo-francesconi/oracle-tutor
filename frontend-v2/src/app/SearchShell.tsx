import { useState } from 'react'
import type { SearchShellState } from '../types/ui'

const INITIAL_STATE: SearchShellState = {
  draftQuery: '',
  submittedQuery: null,
  filters: {},
  results: [],
  hasMore: false,
  isLoading: false,
  isLoadingMore: false,
  selectedCard: null,
}

function buildPlaceholderResults(query: string): string[] {
  return [
    `Placeholder result for “${query}”`,
    `Another result for “${query}”`,
    `A third result for “${query}”`,
  ]
}

export function SearchShell() {
  const [state, setState] = useState<SearchShellState>(INITIAL_STATE)

  const isHome = state.submittedQuery === null
  const isResults = !isHome

  const handleDraftChange = (value: string) => {
    setState((current) => ({
      ...current,
      draftQuery: value,
    }))
  }

  const handleSubmit = () => {
    const nextQuery = state.draftQuery.trim()
    if (!nextQuery) return

    setState((current) => ({
      ...current,
      submittedQuery: nextQuery,
      results: buildPlaceholderResults(nextQuery),
      hasMore: true,
      selectedCard: null,
    }))
  }

  const handleReset = () => {
    setState((current) => ({
      ...current,
      draftQuery: '',
      submittedQuery: null,
      results: [],
      hasMore: false,
      isLoading: false,
      isLoadingMore: false,
      selectedCard: null,
    }))
  }

  return (
    <main className="app-shell">
      <section className="shell-panel">
        <header className="shell-header">
          <p className="eyebrow">Frontend V2</p>
          <h1 className="wordmark">
            Oracle <span className="wordmark-divider">/</span> Tutor
          </h1>
          <p className="shell-copy">
            Phase 1 proves the app shape: one shell, one state owner, two visual states.
          </p>
        </header>

        <section className="state-switcher" aria-label="Phase 1 shell controls">
          <label className="control-block">
            <span className="control-label">Draft Query</span>
            <input
              type="text"
              value={state.draftQuery}
              onChange={(event) => handleDraftChange(event.target.value)}
              placeholder="type a placeholder query"
              className="shell-input"
            />
          </label>

          <div className="control-actions">
            <button type="button" onClick={handleSubmit} className="shell-button">
              Show Results
            </button>
            <button type="button" onClick={handleReset} className="shell-button shell-button-secondary">
              Reset
            </button>
          </div>
        </section>

        <section className={`shell-stage ${isResults ? 'shell-stage-results' : 'shell-stage-home'}`}>
          {isHome ? (
            <section className="view-panel" aria-label="Home state">
              <p className="eyebrow">Home State</p>
              <p className="view-copy">
                The app starts in a single home state. No page split, no route split, no search-box
                complexity yet.
              </p>
              <p className="view-copy">
                Mana symbols still exist in the shell:
                {' '}
                <span className="mana-sample">
                  <i className="ms ms-w" aria-hidden="true" />
                  <i className="ms ms-u" aria-hidden="true" />
                  <i className="ms ms-b" aria-hidden="true" />
                  <i className="ms ms-r" aria-hidden="true" />
                  <i className="ms ms-g" aria-hidden="true" />
                </span>
              </p>
            </section>
          ) : null}

          {isResults ? (
            <section className="view-panel" aria-label="Results state">
              <p className="eyebrow">Results State</p>
              <p className="view-copy">
                Submitted query:
                {' '}
                <strong>{state.submittedQuery}</strong>
              </p>
              <ul className="results-list">
                {state.results.map((result) => (
                  <li key={result} className="results-item">
                    {result}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </section>
      </section>
    </main>
  )
}
