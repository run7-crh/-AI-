import { describe, expect, it } from 'vitest'
import { attachmentTypeLabel, isImageAttachment, MAX_IMAGE_BYTES } from '../attachments'

describe('attachment media utils', () => {
  it('detects image attachments by extension or filename', () => {
    expect(isImageAttachment({ extension: 'jpg' })).toBe(true)
    expect(isImageAttachment({ extension: 'PNG' })).toBe(true)
    expect(isImageAttachment({ extension: '', original_name: 'IMG_0001.webp' })).toBe(true)
    expect(isImageAttachment({ extension: 'pdf' })).toBe(false)
    expect(isImageAttachment({ original_name: 'noext' })).toBe(false)
  })

  it('labels images and text attachments differently', () => {
    expect(attachmentTypeLabel({ extension: 'jpg' })).toBe('图片')
    expect(attachmentTypeLabel({ extension: 'log' })).toBe('LOG')
  })

  it('image size cap matches backend VISION_MAX_IMAGE_BYTES', () => {
    expect(MAX_IMAGE_BYTES).toBe(8 * 1024 * 1024)
  })
})
