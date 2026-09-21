import type { Credentials, FeedbackStats, User } from '@/types'
import { apiFetch } from './http'

export interface AdminLogResponse { lines: string[] }
export interface ImportResponse { count: number; files: string[] }

export async function listUsers(): Promise<User[]> {
  return (await apiFetch('/api/admin/users')).json()
}

export async function createUser(credentials: Credentials): Promise<User> {
  return (await apiFetch('/api/admin/users', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(credentials),
  })).json()
}

export async function setUserActive(userId: string, isActive: boolean): Promise<User> {
  return (await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}/status`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: isActive }),
  })).json()
}

export async function resetUserPassword(userId: string, password: string): Promise<void> {
  await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}/password`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
  })
}

export async function deleteUser(userId: string): Promise<void> {
  await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, { method: 'DELETE' })
}

export async function feedbackStats(): Promise<FeedbackStats> {
  return (await apiFetch('/api/admin/feedback/stats')).json()
}

export async function readLogs(limit = 100): Promise<AdminLogResponse> {
  return (await apiFetch(`/api/admin/logs?limit=${limit}`)).json()
}

export async function importKnowledgeBase(files: File[]): Promise<ImportResponse> {
  const body = new FormData()
  files.forEach((file) => body.append('files', file, file.name))
  return (await apiFetch('/api/admin/knowledge-base/import', { method: 'POST', body })).json()
}
