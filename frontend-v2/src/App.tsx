function App() {
  return (
    <main className="app-shell">
      <section className="placeholder-panel">
        <p className="eyebrow">Frontend V2</p>
        <h1 className="wordmark">
          Oracle <span className="wordmark-divider">/</span> Tutor
        </h1>
        <p className="placeholder-copy">
          Phase 0 establishes the smallest viable app shell.
        </p>
        <p className="placeholder-copy">
          Mana symbols are available:
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
    </main>
  )
}

export default App
