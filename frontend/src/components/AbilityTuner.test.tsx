import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AbilityTuner } from './AbilityTuner'
import type { CardAbility } from '../types/api'
import type { AbilitySelection } from '../types/ui'

const ABILITIES: CardAbility[] = [
  { ability_ix: 0, text: 'Flying', is_keyword: true },
  { ability_ix: 1, text: "Vigilance (Attacking doesn't cause this creature to tap.)", is_keyword: true },
  { ability_ix: 2, text: 'Whenever this creature attacks, draw a card.', is_keyword: false },
]

function renderTuner(selection: AbilitySelection = {}, abilities = ABILITIES) {
  const onCycle = vi.fn()
  const onSet = vi.fn()
  const onReset = vi.fn()
  render(
    <AbilityTuner
      abilities={abilities}
      selection={selection}
      onCycle={onCycle}
      onSet={onSet}
      onReset={onReset}
    />
  )
  return { onCycle, onSet, onReset }
}

/** The tri-state is carried by colour, so state is asserted via the label. */
function ability(name: string) {
  return screen.getByRole('button', { name: new RegExp(`^${name}`) })
}

describe('AbilityTuner', () => {
  it('prints consecutive keywords on one line and rules text on its own', () => {
    renderTuner()

    const keywordLine = ability('Flying').closest('p')
    expect(keywordLine).not.toBeNull()
    expect(keywordLine).toContainElement(ability('Vigilance'))
    expect(keywordLine).not.toContainElement(ability('Whenever'))
  })

  it('strips reminder text from keywords but not from rules text', () => {
    renderTuner()

    expect(ability('Vigilance')).toHaveTextContent(/^Vigilance$/)
    expect(ability('Whenever')).toHaveTextContent('Whenever this creature attacks, draw a card.')
  })

  it('reports each state and the next one in the accessible name', () => {
    renderTuner({ 0: 'include', 1: 'exclude' })

    expect(ability('Flying')).toHaveAccessibleName('Flying — forced. Click to reject it.')
    expect(ability('Vigilance')).toHaveAccessibleName('Vigilance — rejected. Click to clear it.')
    expect(ability('Whenever')).toHaveAccessibleName(/included\. Click to force it\.$/)
  })

  it('cycles the clicked ability only', () => {
    const { onCycle } = renderTuner()

    fireEvent.click(ability('Whenever'))

    expect(onCycle).toHaveBeenCalledExactlyOnceWith(2)
  })

  it('rejects every keyword in one action, leaving rules text alone', () => {
    const { onSet } = renderTuner()

    fireEvent.click(screen.getByRole('button', { name: 'reject keywords' }))

    expect(onSet).toHaveBeenCalledExactlyOnceWith([0, 1], 'exclude')
  })

  it('offers to clear the keywords once they are all rejected', () => {
    const { onSet } = renderTuner({ 0: 'exclude', 1: 'exclude' })

    fireEvent.click(screen.getByRole('button', { name: 'clear keywords' }))

    expect(onSet).toHaveBeenCalledExactlyOnceWith([0, 1], null)
  })

  it('keeps offering to reject while any keyword is untouched', () => {
    renderTuner({ 0: 'exclude' })

    expect(screen.getByRole('button', { name: 'reject keywords' })).toBeInTheDocument()
  })

  it('hides the keyword action on a face with no keywords', () => {
    renderTuner({}, [ABILITIES[2]])

    expect(screen.queryByRole('button', { name: /keywords/ })).toBeNull()
  })

  it('always shows reset tuning, inert until something is tuned', () => {
    const { onReset } = renderTuner()
    const reset = screen.getByRole('button', { name: 'reset tuning' })

    expect(reset).toBeDisabled()
    fireEvent.click(reset)
    expect(onReset).not.toHaveBeenCalled()
  })

  it('enables reset tuning once an ability is tuned', () => {
    const { onReset } = renderTuner({ 2: 'include' })
    const reset = screen.getByRole('button', { name: 'reset tuning' })

    expect(reset).toBeEnabled()
    fireEvent.click(reset)
    expect(onReset).toHaveBeenCalledOnce()
  })

  it('teaches the interaction only while untouched', () => {
    const { unmount } = render(
      <AbilityTuner abilities={ABILITIES} selection={{}} onCycle={vi.fn()} onSet={vi.fn()} onReset={vi.fn()} />
    )
    expect(screen.getByText('click to force · again to reject')).toBeInTheDocument()
    unmount()

    renderTuner({ 2: 'include' })
    expect(screen.queryByText('click to force · again to reject')).toBeNull()
  })

  it('warns when every ability is rejected, since the search has no seed left', () => {
    renderTuner({ 0: 'exclude', 1: 'exclude', 2: 'exclude' })

    expect(
      screen.getByText('every ability is rejected — nothing left to search by')
    ).toBeInTheDocument()
  })
})
