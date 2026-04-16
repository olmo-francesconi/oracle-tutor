import { DenseTextBackground } from '../components/background/DenseTextBackground'
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
      <DenseTextBackground
        texts={oracleSamples.texts}
        viewport={viewport}
        isVisible={hasOracleBackground}
        leftInset={LEFT_STRIPE_WIDTH_PX}
      />
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
    </>
  )
}
