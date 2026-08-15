import type { CardAbility } from '../types/api'
import type { AbilityChoice, AbilitySelection } from '../types/ui'
import { SymbolText } from './SymbolText'

type Props = {
  abilities: CardAbility[]
  selection: AbilitySelection
  onCycle: (abilityIx: number) => void
  onSet: (abilityIxs: number[], choice: AbilityChoice | null) => void
  onReset: () => void
}

type AbilityState = AbilityChoice | 'none'

// State is carried by color alone: ink = kept as printed, green = forced,
// red = rejected. Screen readers get the state from the aria-label instead.
const STATE_CLASS: Record<AbilityState, string> = {
  none: 'text-ot-ink',
  include: 'text-ot-green',
  exclude: 'text-ot-red',
}

const STATE_LABEL: Record<AbilityState, string> = {
  none: 'included',
  include: 'forced',
  exclude: 'rejected',
}

const NEXT_LABEL: Record<AbilityState, string> = {
  none: 'force it',
  include: 'reject it',
  exclude: 'clear it',
}

const REMINDER_TEXT = /\s*\([^)]*\)/g

/** Keywords print as one comma-separated line, so they render as one too. */
type Row = { kind: 'keywords'; items: CardAbility[] } | { kind: 'ability'; item: CardAbility }

function groupAbilities(abilities: CardAbility[]): Row[] {
  const rows: Row[] = []
  for (const ability of abilities) {
    if (!ability.is_keyword) {
      rows.push({ kind: 'ability', item: ability })
      continue
    }
    const last = rows[rows.length - 1]
    if (last?.kind === 'keywords') last.items.push(ability)
    else rows.push({ kind: 'keywords', items: [ability] })
  }
  return rows
}

const BUTTON_CLASS =
  'cursor-pointer border-0 bg-transparent p-0 text-left underline-offset-4 transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:underline hover:decoration-dotted motion-reduce:transition-none'

// Cursor and color are set per-button so the disabled variant can't lose a
// Tailwind source-order coin flip against `cursor-pointer` / `hover:`.
const ACTION_CLASS =
  'border-0 bg-transparent p-0 text-[0.7rem] lowercase tracking-[0.04em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none'
const ACTION_ENABLED = 'cursor-pointer text-ot-muted hover:text-ot-red'

export function AbilityTuner({ abilities, selection, onCycle, onSet, onReset }: Props) {
  const tunedCount = Object.keys(selection).length
  // Rejecting everything the card does leaves the search with no seed, so say
  // so here rather than letting it read as "no cards matched".
  const allExcluded = abilities.every((a) => selection[a.ability_ix] === 'exclude')

  const keywordIxs = abilities.filter((a) => a.is_keyword).map((a) => a.ability_ix)
  const keywordsRejected =
    keywordIxs.length > 0 && keywordIxs.every((ix) => selection[ix] === 'exclude')

  const renderButton = (ability: CardAbility, text: string, extraClass: string) => {
    const state: AbilityState = selection[ability.ability_ix] ?? 'none'
    return (
      <button
        type="button"
        onClick={() => onCycle(ability.ability_ix)}
        aria-label={`${text} — ${STATE_LABEL[state]}. Click to ${NEXT_LABEL[state]}.`}
        className={[BUTTON_CLASS, STATE_CLASS[state], extraClass].join(' ')}
      >
        <SymbolText text={text} />
      </button>
    )
  }

  return (
    <div className="grid content-start gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="eyebrow">Abilities</p>
        <div className="flex items-baseline gap-2">
          {keywordIxs.length > 0 ? (
            <button
              type="button"
              onClick={() => onSet(keywordIxs, keywordsRejected ? null : 'exclude')}
              className={[
                ACTION_CLASS,
                keywordsRejected ? 'cursor-pointer text-ot-red' : ACTION_ENABLED,
              ].join(' ')}
            >
              {keywordsRejected ? 'clear keywords' : 'reject keywords'}
            </button>
          ) : null}
          {keywordIxs.length > 0 ? (
            <span aria-hidden="true" className="text-[0.7rem] text-ot-line">
              ·
            </span>
          ) : null}
          <button
            type="button"
            onClick={onReset}
            disabled={tunedCount === 0}
            className={[
              ACTION_CLASS,
              tunedCount === 0 ? 'cursor-default text-ot-line' : ACTION_ENABLED,
            ].join(' ')}
          >
            reset tuning
          </button>
        </div>
      </div>

      <div className="grid gap-1 text-[0.85rem] leading-[1.55]">
        {groupAbilities(abilities).map((row) =>
          row.kind === 'keywords' ? (
            <p key={`kw-${row.items[0].ability_ix}`} className="m-0 flex flex-wrap items-baseline">
              {row.items.map((ability, index) => (
                <span key={ability.ability_ix} className="whitespace-nowrap">
                  {/* Reminder text is noise at chip size and the card art is right there. */}
                  {renderButton(ability, ability.text.replace(REMINDER_TEXT, '').trim(), '')}
                  {index < row.items.length - 1 ? (
                    <span className="pr-1 text-ot-muted">,</span>
                  ) : null}
                </span>
              ))}
            </p>
          ) : (
            <div key={row.item.ability_ix}>
              {renderButton(row.item, row.item.text, 'block w-full whitespace-pre-line')}
            </div>
          )
        )}
      </div>

      {allExcluded ? (
        <p className="m-0 text-[0.7rem] lowercase tracking-[0.04em] text-ot-red">
          every ability is rejected — nothing left to search by
        </p>
      ) : tunedCount === 0 ? (
        <p className="m-0 text-[0.7rem] lowercase tracking-[0.04em] text-ot-muted">
          click to force · again to reject
        </p>
      ) : null}
    </div>
  )
}
