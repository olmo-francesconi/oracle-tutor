import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AdminRangeField } from './AdminRangeField'

describe('AdminRangeField', () => {
  it('renders each option marker and forwards range changes', () => {
    const handleChange = vi.fn()

    render(
      <AdminRangeField
        label="Epochs"
        value={4}
        options={[2, 4, 6]}
        rangeValue={2}
        rangeMin={0}
        rangeMax={2}
        onChange={handleChange}
      />
    )

    expect(screen.getByText('Epochs')).toBeInTheDocument()
    expect(screen.getAllByText('4')).toHaveLength(2)
    expect(screen.getByRole('slider')).toHaveValue('2')

    fireEvent.change(screen.getByRole('slider'), { target: { value: '1' } })

    expect(handleChange).toHaveBeenCalledWith(1)
  })
})
