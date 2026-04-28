import { useState, type FormEvent } from 'react'
import { exchangeAdminPasswordForToken } from '../lib/adminApi'

type AdminLoginProps = {
  onSuccess: () => void
}

export function AdminLogin({ onSuccess }: AdminLoginProps) {
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      await exchangeAdminPasswordForToken(password)
      onSuccess()
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to sign in.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-ot-bg px-4 text-ot-ink">
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        aria-hidden="true"
        style={{
          backgroundImage:
            'repeating-linear-gradient(to bottom, transparent 0, transparent 70px, rgba(17,17,17,0.05) 70px, rgba(17,17,17,0.05) 72px)',
        }}
      />
      <div className="relative z-10 w-full max-w-xl border-2 border-ot-ink bg-ot-surface">
        <div className="border-b-2 border-ot-ink px-6 py-5">
          <p className="eyebrow">Semantic Registry / Admin</p>
          <h1 className="m-0 pt-2 font-display text-[clamp(2.6rem,9vw,4.8rem)] font-black uppercase leading-[0.84] tracking-[-0.04em]">
            Operator login
          </h1>
        </div>
        <form onSubmit={handleSubmit} className="grid gap-0">
          <label className="grid gap-2 border-b-2 border-ot-ink px-6 py-5">
            <span className="eyebrow">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="min-h-12 border-2 border-ot-ink bg-ot-bg px-3 py-2 text-[0.95rem] outline-none transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] focus:bg-ot-surface"
              autoComplete="current-password"
              required
            />
          </label>
          {error ? (
            <div className="border-b-2 border-ot-ink bg-ot-bg px-6 py-4 text-[0.76rem] uppercase tracking-[0.08em] text-ot-red">
              {error}
            </div>
          ) : null}
          <div className="flex items-center justify-between gap-4 px-6 py-5 max-[640px]:flex-col max-[640px]:items-stretch">
            <p className="m-0 text-[0.76rem] uppercase tracking-[0.08em] text-ot-muted">
              Access is restricted to admin operators.
            </p>
            <button
              type="submit"
              disabled={submitting || !password.trim()}
              className="border-2 border-ot-ink bg-ot-red px-5 py-3 font-display text-[1rem] font-black uppercase tracking-[-0.02em] text-ot-bg disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </div>
        </form>
      </div>
    </main>
  )
}
