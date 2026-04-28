import type { Dispatch, FormEvent, SetStateAction } from 'react'
import type { SemanticTrainAugmentationOption } from '../types/api'
import type { DatasetFormState } from './adminForms'
import { AdminSelectionField } from './AdminSelectionField'

type Props = {
  form: DatasetFormState
  setForm: Dispatch<SetStateAction<DatasetFormState>>
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  submitting: boolean
  loading: boolean
  augmentationOptions: SemanticTrainAugmentationOption[]
}

export function DatasetForm({ form, setForm, onSubmit, submitting, loading, augmentationOptions }: Props) {
  return (
    <form onSubmit={onSubmit} className="grid h-fit gap-0 border-2 border-ot-ink bg-ot-surface">
      <div className="border-b-2 border-ot-ink px-5 py-4">
        <p className="eyebrow">New dataset build</p>
        <h2 className="m-0 pt-2 font-display text-[2.4rem] font-black uppercase leading-[0.88] tracking-[-0.03em]">
          Build a dataset
        </h2>
      </div>

      <label className="grid gap-2 border-b-2 border-ot-ink px-5 py-4">
        <span className="eyebrow">Dataset slug</span>
        <input
          value={form.dataset_slug}
          onChange={(event) => setForm((c) => ({ ...c, dataset_slug: event.target.value }))}
          className="min-h-12 w-full min-w-0 border-2 border-ot-ink bg-ot-bg px-3 py-2 text-[0.95rem] outline-none transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] focus:border-ot-red focus:bg-ot-surface"
          placeholder="v3-llm-aug"
          required
        />
      </label>

      <AdminSelectionField
        legend="Augmentation mode"
        name="dataset_augmentation"
        selectionMode="multiple"
        options={augmentationOptions.map((o) => ({ value: o.key, label: o.label, description: o.description }))}
        value={form.augmentation_keys}
        onChange={(keys) => setForm((c) => ({ ...c, augmentation_keys: keys as string[] }))}
      />

      <div className="px-5 py-4">
        <button
          type="submit"
          disabled={submitting || loading}
          className="min-h-12 w-full cursor-pointer border-2 border-ot-ink bg-ot-bg px-4 py-2 font-display text-[1rem] font-black uppercase tracking-[-0.02em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg active:opacity-80 disabled:cursor-not-allowed disabled:border-ot-line disabled:text-ot-muted"
        >
          {submitting ? 'Queueing…' : 'Queue dataset job'}
        </button>
      </div>
    </form>
  )
}
