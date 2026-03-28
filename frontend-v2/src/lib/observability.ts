const ERROR_REPORTING_URL = import.meta.env.VITE_ERROR_REPORTING_URL
const ANALYTICS_URL = import.meta.env.VITE_ANALYTICS_URL

type ErrorContext = Record<string, unknown>
type AnalyticsProps = Record<string, unknown>
type AnalyticsEventName =
  | 'search_submitted'
  | 'filters_changed'
  | 'filters_cleared'
  | 'load_more_requested'
  | 'card_opened'

type ErrorPayload = {
  message: string
  name: string
  stack?: string
  context?: ErrorContext
  url: string
  userAgent: string
  timestamp: string
}

type AnalyticsPayload = {
  event: AnalyticsEventName
  props?: AnalyticsProps
  url: string
  userAgent: string
  timestamp: string
}

function toErrorPayload(error: unknown, context?: ErrorContext): ErrorPayload {
  if (error instanceof Error) {
    return {
      message: error.message,
      name: error.name,
      stack: error.stack,
      context,
      url: window.location.href,
      userAgent: window.navigator.userAgent,
      timestamp: new Date().toISOString(),
    }
  }

  return {
    message: typeof error === 'string' ? error : 'Unknown runtime error',
    name: 'UnknownError',
    context,
    url: window.location.href,
    userAgent: window.navigator.userAgent,
    timestamp: new Date().toISOString(),
  }
}

function toAnalyticsPayload(event: AnalyticsEventName, props?: AnalyticsProps): AnalyticsPayload {
  return {
    event,
    props,
    url: window.location.href,
    userAgent: window.navigator.userAgent,
    timestamp: new Date().toISOString(),
  }
}

export function reportError(error: unknown, context?: ErrorContext) {
  const payload = toErrorPayload(error, context)

  if (import.meta.env.DEV) {
    console.error('[ot-runtime-error]', payload)
  }

  if (!ERROR_REPORTING_URL) return

  void fetch(ERROR_REPORTING_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {
    // Intentionally ignore reporting failures so they never affect the UI.
  })
}

export function track(event: AnalyticsEventName, props?: AnalyticsProps) {
  const payload = toAnalyticsPayload(event, props)

  if (import.meta.env.DEV) {
    console.info('[ot-analytics]', payload)
  }

  if (!ANALYTICS_URL) return

  void fetch(ANALYTICS_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {
    // Intentionally ignore analytics failures.
  })
}

export function setupGlobalErrorHandlers() {
  const handleWindowError = (event: ErrorEvent) => {
    reportError(event.error ?? event.message, {
      source: 'window.error',
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
    })
  }

  const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
    reportError(event.reason, {
      source: 'window.unhandledrejection',
    })
  }

  window.addEventListener('error', handleWindowError)
  window.addEventListener('unhandledrejection', handleUnhandledRejection)

  return () => {
    window.removeEventListener('error', handleWindowError)
    window.removeEventListener('unhandledrejection', handleUnhandledRejection)
  }
}
