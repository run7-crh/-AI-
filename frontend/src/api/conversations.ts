// frontend/src/api/conversations.ts
import type { Conversation, ConversationDetail } from '@/types'

async function ensureOk(r: Response): Promise<Response> {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r
}

export async function listConversations(): Promise<Conversation[]> {
  const r = await fetch('/api/conversations')
  await ensureOk(r)
  return r.json()
}

export async function createConversation(body: { title?: string } = {}): Promise<Conversation> {
  const r = await fetch('/api/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await ensureOk(r)
  return r.json()
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const r = await fetch(`/api/conversations/${id}`)
  await ensureOk(r)
  return r.json()
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`/api/conversations/${id}`, { method: 'DELETE' })
  await ensureOk(r)
}

export async function updateConversation(id: string, title: string): Promise<Conversation> {
  const r = await fetch(`/api/conversations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  await ensureOk(r)
  return r.json()
}
