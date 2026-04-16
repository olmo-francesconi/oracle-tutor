type AdminRangeFieldProps = {
  label: string
  value: number
  options: number[]
  rangeValue: number
  rangeMin: number
  rangeMax: number
  onChange: (nextRangeValue: number) => void
}

function markerPosition(index: number, total: number) {
  if (total <= 1) return '8px'
  return `calc(8px + ${(index / (total - 1)).toFixed(4)} * (100% - 16px))`
}

export function AdminRangeField({
  label,
  value,
  options,
  rangeValue,
  rangeMin,
  rangeMax,
  onChange,
}: AdminRangeFieldProps) {
  const currentIndex = Math.max(0, Math.min(options.length - 1, rangeValue - rangeMin))
  const progress = options.length > 1 ? currentIndex / (options.length - 1) : 0
  const progressWidth = `calc(${progress.toFixed(4)} * (100% - 16px))`
  const knobPosition = markerPosition(currentIndex, options.length)

  return (
    <div className="grid gap-3 border-b-2 border-ot-ink px-5 py-4">
      <div className="flex items-baseline justify-between gap-4">
        <span className="eyebrow">{label}</span>
        <span className="font-display text-[2.4rem] font-black leading-none tracking-[-0.04em]">{value}</span>
      </div>
      <div className="grid gap-1">
        <div className="relative h-5">
          <div className="absolute inset-x-2 top-1/2 h-0.5 -translate-y-1/2 bg-ot-line" />
          {options.map((option, index) => (
            <div
              key={option}
              className="absolute top-1/2 h-[6px] w-[6px] -translate-x-1/2 -translate-y-1/2 bg-ot-line"
              style={{ left: markerPosition(index, options.length) }}
            />
          ))}
          <div
            className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-ot-ink"
            style={{ left: '8px', width: progressWidth }}
          />
          <div
            className="pointer-events-none absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 bg-ot-ink transition-[left] duration-75"
            style={{ left: knobPosition }}
          />
          <input
            type="range"
            min={rangeMin}
            max={rangeMax}
            step={1}
            value={rangeValue}
            onChange={(event) => onChange(Number(event.target.value))}
            className="ot-slider absolute inset-0 h-full w-full focus-visible:outline-none"
          />
        </div>
        <div className="relative h-4">
          {options.map((option, index) => (
            <span
              key={option}
              className="absolute -translate-x-1/2 text-[0.6rem] uppercase tracking-[0.04em] text-ot-muted"
              style={{ left: markerPosition(index, options.length) }}
            >
              {option}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
