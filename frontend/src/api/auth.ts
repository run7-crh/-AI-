import type { Credentials, User } from '@/types'
import { apiFetch, markAuthenticated } from './http'

export async function register(credentials: Credentials): Promise<User> {
  const user = await (await apiFetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  })).json() as User
  markAuthenticated()
  return user
}

export async function login(credentials: Credentials): Promise<User> {
  const user = await (await apiFetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  })).json() as User
  markAuthenticated()
  return user
}

export async function logout(): Promise<void> {
  await apiFetch('/api/auth/logout', { method: 'POST' })
}

export async function me(): Promise<User> {
  return (await apiFetch('/api/auth/me')).json()
}
