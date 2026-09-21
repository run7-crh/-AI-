export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail || `HTTP ${status}`
  }
}

let authExpiredDispatched = false

export function markAuthenticated(): void {
  authExpiredDispatched = false
}

export function notifyAuthExpired(): void {
  if (authExpiredDispatched) return
  authExpiredDispatched = true
  window.dispatchEvent(new Event('auth-expired'))
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(input, { ...init, credentials: 'include' })
  if (response.ok) {
    return response
  }
  let detail = `HTTP ${response.status}`
  try {
    const body = await response.clone().json() as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    // Keep the status-derived detail for non-JSON responses.
  }
  if (response.status === 401) notifyAuthExpired()
  throw new ApiError(response.status, detail)
}

export async function apiJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  return (await apiFetch(input, init)).json() as Promise<T>
}
