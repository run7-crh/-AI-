import type { Attachment } from '@/types'
import { ApiError, apiFetch, notifyAuthExpired } from './http'

export interface AttachmentUploadResponse {
  attachments: Attachment[]
  count?: number
  total_size_bytes?: number
  total_extracted_chars?: number
}

export type UploadProgress = (percent: number) => void

async function ensureOk(response: Response): Promise<Response> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response
}

/**
 * Upload one or more temporary conversation attachments.
 * XMLHttpRequest is used because fetch does not expose upload progress in
 * browsers. The response contains metadata only; extracted text is private.
 */
export function uploadAttachments(
  conversationId: string,
  files: File[],
  onProgress?: UploadProgress,
): Promise<AttachmentUploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const form = new FormData()
    for (const file of files) form.append('files', file, file.name)

    xhr.open('POST', `/api/conversations/${encodeURIComponent(conversationId)}/attachments`)
    xhr.withCredentials = true
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)))
    }
    xhr.onload = () => {
      let body: AttachmentUploadResponse & { detail?: string }
      try {
        const rawResponse = typeof xhr.response === 'string' ? xhr.response : xhr.responseText
        body = xhr.response && typeof xhr.response === 'object'
          ? xhr.response as AttachmentUploadResponse & { detail?: string }
          : JSON.parse(rawResponse || '{}') as AttachmentUploadResponse & { detail?: string }
      } catch {
        reject(new Error('附件服务返回了无效响应'))
        return
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = body.detail || `HTTP ${xhr.status}`
        if (xhr.status === 401) notifyAuthExpired()
        reject(new ApiError(xhr.status, detail))
        return
      }
      onProgress?.(100)
      resolve(body)
    }
    xhr.onerror = () => reject(new Error('附件上传失败，请重试'))
    xhr.onabort = () => reject(new DOMException('附件上传已取消', 'AbortError'))
    xhr.send(form)
  })
}

export async function listAttachments(conversationId: string): Promise<Attachment[]> {
  const response = await ensureOk(await apiFetch(`/api/conversations/${encodeURIComponent(conversationId)}/attachments`))
  return response.json()
}

export async function getAttachment(conversationId: string, attachmentId: string): Promise<Attachment> {
  const response = await ensureOk(await apiFetch(
    `/api/conversations/${encodeURIComponent(conversationId)}/attachments/${encodeURIComponent(attachmentId)}`,
  ))
  return response.json()
}

export async function deleteAttachment(conversationId: string, attachmentId: string): Promise<void> {
  await ensureOk(await apiFetch(
    `/api/conversations/${encodeURIComponent(conversationId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { method: 'DELETE' },
  ))
}
