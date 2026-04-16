type AdminSelectionOption = {
  value: string
  label: string
  description?: string
}

type AdminSelectionFieldProps = {
  legend: string
  name: string
  options: AdminSelectionOption[]
  selectionMode: 'single' | 'multiple'
  value: string | string[]
  onChange: (nextValue: string | string[]) => void
  columnsClassName?: string
  className?: string
}

export function AdminSelectionField({
  legend,
  name,
  options,
  selectionMode,
  value,
  onChange,
  columnsClassName = 'grid-cols-2 max-[640px]:grid-cols-1',
  className = '',
}: AdminSelectionFieldProps) {
  const selectedValues = selectionMode === 'multiple' ? new Set(value as string[]) : new Set([value as string])

  return (
    <fieldset className={`grid gap-3 border-b-2 border-ot-ink px-5 py-4 ${className}`}>
      <legend className="eyebrow px-0">{legend}</legend>
      <div className={`grid gap-3 ${columnsClassName}`}>
        {options.map((option) => {
          const checked = selectedValues.has(option.value)

          return (
            <label
              key={option.value}
              className={`grid min-w-0 cursor-pointer gap-2 border-2 px-3 py-3 transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] active:opacity-80 ${
                checked
                  ? 'border-ot-ink bg-[color-mix(in_srgb,var(--color-ot-red)_5%,var(--color-ot-surface))] focus-within:border-ot-red'
                  : 'border-ot-line bg-ot-bg hover:border-ot-ink focus-within:border-ot-red'
              }`}
            >
              <span className="flex items-start gap-3">
                <input
                  type={selectionMode === 'single' ? 'radio' : 'checkbox'}
                  name={name}
                  value={option.value}
                  checked={checked}
                  onChange={() => {
                    if (selectionMode === 'single') {
                      onChange(option.value)
                      return
                    }

                    const nextValues = new Set(selectedValues)
                    if (checked) {
                      nextValues.delete(option.value)
                    } else {
                      nextValues.add(option.value)
                    }
                    onChange(Array.from(nextValues))
                  }}
                  className="mt-[2px] h-4 w-4 shrink-0 accent-ot-red"
                />
                <span className="grid min-w-0 gap-1">
                  <span className="font-display text-[1rem] font-black uppercase leading-none tracking-[-0.02em]">
                    {option.label}
                  </span>
                  {option.description ? (
                    <span className="break-words text-[0.72rem] uppercase leading-[1.45] tracking-[0.08em] text-ot-muted">
                      {option.description}
                    </span>
                  ) : null}
                </span>
              </span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
