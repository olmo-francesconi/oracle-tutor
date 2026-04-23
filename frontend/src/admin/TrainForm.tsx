import type { FormEvent } from 'react'
import type {
  SemanticBaseModelOption,
  SemanticDatasetSummary,
  SemanticTrainOptions,
} from '../types/api'
import { AdminRangeField } from './AdminRangeField'
import { AdminSelect } from './AdminSelect'
import type { TrainFormState } from './adminForms'

type Props = {
  form: TrainFormState
  onFieldChange: <K extends keyof TrainFormState>(key: K, value: TrainFormState[K]) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  submitting: boolean
  loading: boolean
  baseModels: SemanticBaseModelOption[]
  trainOptions: SemanticTrainOptions
  selectedBaseModel: SemanticBaseModelOption | null
  datasets: SemanticDatasetSummary[]
}

export function TrainForm({
  form,
  onFieldChange,
  onSubmit,
  submitting,
  loading,
  baseModels,
  trainOptions,
  selectedBaseModel,
  datasets,
}: Props) {
  const readyDatasets = datasets.filter((ds) => ds.status === 'ready')

  return (
    <form onSubmit={onSubmit} className="grid h-fit gap-0 border-2 border-ot-ink bg-ot-surface">
      <div className="border-b-2 border-ot-ink px-5 py-4">
        <p className="eyebrow">New train run</p>
        <h2 className="m-0 pt-2 font-display text-[2.4rem] font-black uppercase leading-[0.88] tracking-[-0.03em]">
          Queue a candidate
        </h2>
      </div>

      <label className="grid gap-2 border-b-2 border-ot-ink px-5 py-4">
        <span className="eyebrow">Model slug</span>
        <input
          value={form.model_slug}
          onChange={(event) => onFieldChange('model_slug', event.target.value)}
          className="min-h-12 w-full min-w-0 border-2 border-ot-ink bg-ot-bg px-3 py-2 text-[0.95rem] outline-none transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] focus:border-ot-red focus:bg-ot-surface"
          placeholder="oracle-tutor-smoke"
          required
        />
      </label>

      <div className="grid gap-2 border-b-2 border-ot-ink px-5 py-4">
        <span className="eyebrow">Base model</span>
        <AdminSelect
          label="Base model"
          options={baseModels.map((m) => ({ value: m.key, label: m.label }))}
          value={form.base_model_key}
          placeholder="Select base model"
          onChange={(v) => onFieldChange('base_model_key', v)}
        />
        {selectedBaseModel ? (
          <span className="break-words text-[0.76rem] uppercase leading-[1.45] tracking-[0.08em] text-ot-muted">
            {selectedBaseModel.base_model} / dim {selectedBaseModel.embedding_dim}
          </span>
        ) : null}
      </div>

      <AdminRangeField
        label="Epochs"
        value={form.epochs}
        options={Array.from(
          { length: trainOptions.epoch_max - trainOptions.epoch_min + 1 },
          (_, index) => trainOptions.epoch_min + index
        )}
        rangeValue={form.epochs}
        rangeMin={trainOptions.epoch_min}
        rangeMax={trainOptions.epoch_max}
        onChange={(nextValue) => onFieldChange('epochs', nextValue)}
      />

      <AdminRangeField
        label="Batch size"
        value={form.batch_size}
        options={trainOptions.batch_size_options}
        rangeValue={Math.max(0, trainOptions.batch_size_options.indexOf(form.batch_size))}
        rangeMin={0}
        rangeMax={Math.max(0, trainOptions.batch_size_options.length - 1)}
        onChange={(nextValue) => {
          const selectedValue = trainOptions.batch_size_options[nextValue]
          if (selectedValue !== undefined) {
            onFieldChange('batch_size', selectedValue)
          }
        }}
      />

      <AdminRangeField
        label="Embed batch size"
        value={form.embed_batch_size}
        options={trainOptions.embed_batch_size_options}
        rangeValue={Math.max(0, trainOptions.embed_batch_size_options.indexOf(form.embed_batch_size))}
        rangeMin={0}
        rangeMax={Math.max(0, trainOptions.embed_batch_size_options.length - 1)}
        onChange={(nextValue) => {
          const selectedValue = trainOptions.embed_batch_size_options[nextValue]
          if (selectedValue !== undefined) {
            onFieldChange('embed_batch_size', selectedValue)
          }
        }}
      />

      <div className="grid gap-2 border-b-2 border-ot-ink px-5 py-4">
        <span className="eyebrow">Dataset</span>
        {readyDatasets.length === 0 ? (
          <p className="m-0 text-[0.76rem] uppercase tracking-[0.08em] text-ot-muted">
            No ready datasets yet — build one above.
          </p>
        ) : (
          <AdminSelect
            label="Dataset"
            options={readyDatasets.map((ds) => ({ value: String(ds.id), label: `${ds.slug} (${ds.augmentation_mode})` }))}
            value={form.dataset_id}
            placeholder="Choose a dataset"
            onChange={(v) => onFieldChange('dataset_id', v)}
          />
        )}
      </div>

      <div className="grid border-b-2 border-ot-ink">
        <label className="flex cursor-pointer items-start gap-3 bg-[color-mix(in_srgb,var(--color-ot-red)_5%,var(--color-ot-surface))] px-5 py-4">
          <input
            type="checkbox"
            checked={form.skip_fine_tune}
            onChange={(event) => onFieldChange('skip_fine_tune', event.target.checked)}
            className="mt-[2px] h-4 w-4 accent-ot-red"
          />
          <span className="grid gap-1">
            <span className="font-display text-[1.2rem] font-black uppercase leading-none tracking-[-0.02em]">
              Base-model smoke run
            </span>
            <span className="text-[0.76rem] uppercase leading-[1.45] tracking-[0.08em] text-ot-muted">
              Skip fine-tuning and register an ONNX bundle built directly from the base model.
            </span>
          </span>
        </label>

        <label className="flex cursor-pointer items-start gap-3 border-t-2 border-ot-ink px-5 py-4">
          <input
            type="checkbox"
            checked={form.promote_after_register}
            onChange={(event) => onFieldChange('promote_after_register', event.target.checked)}
            className="mt-[2px] h-4 w-4 accent-ot-red"
          />
          <span className="grid gap-1">
            <span className="font-display text-[1.2rem] font-black uppercase leading-none tracking-[-0.02em]">
              Queue promotion after register
            </span>
            <span className="text-[0.76rem] uppercase leading-[1.45] tracking-[0.08em] text-ot-muted">
              If the promote lane is occupied, training still succeeds and the warning is recorded with the job.
            </span>
          </span>
        </label>
      </div>

      <div className="grid gap-3 px-5 py-4">
        <button
          type="submit"
          disabled={submitting || loading}
          className="min-h-14 cursor-pointer border-2 border-ot-ink bg-ot-ink px-4 py-3 font-display text-[1.15rem] font-black uppercase tracking-[-0.02em] text-ot-bg transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-red active:opacity-80 disabled:cursor-not-allowed disabled:bg-ot-muted"
        >
          {submitting ? 'Queueing…' : 'Queue train job'}
        </button>
        <p className="m-0 text-[0.72rem] uppercase leading-[1.55] tracking-[0.08em] text-ot-muted">
          Defaulted for fast operator loops: the smoke-run toggle starts on so you can validate the stack before burning a slow fine-tune.
        </p>
      </div>
    </form>
  )
}
