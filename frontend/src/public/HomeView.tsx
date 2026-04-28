import { HomeEditorialText } from '../components/background/HomeEditorialText'
import { SearchBox } from '../components/SearchBox/SearchBox'
import type { CardMatch, OracleSamples } from '../types/api'

const LEFT_STRIPE_WIDTH_PX = 6

type ViewportSize = {
  width: number
  height: number
}

type Props = {
  draftQuery: string
  oracleSamples: OracleSamples
  viewport: ViewportSize
  hasOracleBackground: boolean
  onDraftChange: (value: string) => void
  onSubmit: (value?: string) => void
  onCardSelect: (card: CardMatch) => void
}

export function HomeView({
  draftQuery,
  oracleSamples,
  viewport,
  hasOracleBackground,
  onDraftChange,
  onSubmit,
  onCardSelect,
}: Props) {
  return (
    <>
      <div className="relative z-10">
        <HomeEditorialText
          texts={oracleSamples.texts}
          terms={oracleSamples.terms}
          viewport={viewport}
          isVisible={hasOracleBackground}
          leftInset={LEFT_STRIPE_WIDTH_PX}
        />

        <div className="fixed inset-y-0 left-0 z-20 w-1.5 bg-ot-red" aria-hidden="true" />

        <section className="relative z-20 grid w-full max-w-[560px] gap-7" aria-label="Home state">
          <div className="grid gap-3 px-[18px] text-left max-[720px]:px-[14px]">
            <h1 className="m-0 font-display text-[clamp(4.5rem,11vw,7rem)] font-black uppercase leading-[0.86] tracking-[-0.03em]">
              <span className="block">Oracle</span>
              <span className="block">Tutor</span>
            </h1>
            <div className="h-0.5 w-full max-w-[18.5rem] bg-ot-ink" />
            <p className="m-0 max-w-[30ch] text-[0.8125rem] lowercase leading-[1.55] tracking-[0.06em] text-ot-muted">
              find cards by meaning, not keywords.
            </p>
          </div>

          <div className="grid gap-0">
            <SearchBox
              value={draftQuery}
              onChange={onDraftChange}
              onSubmit={onSubmit}
              onCardSelect={onCardSelect}
              autoFocus
              showManaRail
              variant="home"
            />
          </div>
        </section>
      </div>

      <footer
        className="fixed bottom-3 right-4 z-30 text-[0.6875rem] lowercase tracking-[0.08em] text-ot-muted max-[720px]:bottom-2 max-[720px]:right-2"
        aria-label="Attribution"
      >
        <span>
          data from{' '}
          <a
            href="https://scryfall.com"
            target="_blank"
            rel="noreferrer"
            className="underline decoration-ot-muted/40 underline-offset-[3px] hover:text-ot-ink hover:decoration-ot-ink"
          >
            scryfall
          </a>
          , built by olmo
        </span>
        <span className="ml-2 inline-flex items-center gap-2 align-middle">
          <a
            href="https://github.com/olmo-francesconi"
            target="_blank"
            rel="noreferrer"
            aria-label="GitHub repository"
            className="hover:text-ot-ink"
          >
            <svg
              viewBox="0 0 16 16"
              width="13"
              height="13"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 005.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.42 7.42 0 014 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
          </a>
          <a
            href="https://www.linkedin.com/in/olmo-francesconi"
            target="_blank"
            rel="noreferrer"
            aria-label="LinkedIn profile"
            className="hover:text-ot-ink"
          >
            <svg
              viewBox="0 0 24 24"
              width="13"
              height="13"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.13 1.45-2.13 2.94v5.67H9.37V9h3.41v1.56h.05c.47-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.45v6.29zM5.34 7.43a2.06 2.06 0 110-4.13 2.06 2.06 0 010 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z" />
            </svg>
          </a>
        </span>
      </footer>
    </>
  )
}
