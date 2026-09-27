/** 附件媒体类型判定与展示文案（InputBox / UserMessage / SourceCard 共用）。 */

/** 与后端 attachment_security.IMAGE_EXTENSIONS 对应的图片扩展名。 */
export const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp'])

/** 与后端 VISION_MAX_IMAGE_BYTES 同步的单图上限（字节）。 */
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024

export function isImageAttachment(target: { extension?: string | null; original_name?: string | null }): boolean {
  const extension = (target.extension || '').toLowerCase()
  if (extension) return IMAGE_EXTENSIONS.has(extension)
  const name = target.original_name || ''
  const dot = name.lastIndexOf('.')
  return dot !== -1 && IMAGE_EXTENSIONS.has(name.slice(dot + 1).toLowerCase())
}

/** 附件类型短标签：图片显示"图片"，其余显示大写扩展名。 */
export function attachmentTypeLabel(target: { extension?: string | null; original_name?: string | null }): string {
  return isImageAttachment(target) ? '图片' : (target.extension || '').toUpperCase()
}

/** 附件上传失败码 → 用户可读文案（其余原样透出）。 */
export const ATTACHMENT_ERROR_LABELS: Record<string, string> = {
  image_upload_disabled: '图片上传未启用：需在后端开启视觉观察（VISION_ENABLED）',
  image_too_large: '图片超过大小上限（8MB）',
  signature_invalid: '文件已损坏或扩展名与实际内容不符',
}
