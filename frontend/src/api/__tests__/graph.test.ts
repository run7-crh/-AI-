import { afterEach, expect, it, vi } from 'vitest'
import { fetchGraph, GraphNotBuiltError, rebuildIndex } from '../graph'
import { ApiError } from '../http'

afterEach(() => vi.unstubAllGlobals())

it('preserves the graph not built error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 404 })))
  await expect(fetchGraph()).rejects.toBeInstanceOf(GraphNotBuiltError)
})

it('preserves the friendly rate limit message and structured status', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 429 })))
  await expect(rebuildIndex()).rejects.toMatchObject({ status: 429, detail: '重建请求过于频繁，请稍后再试' })
})

it('keeps authentication failures structured', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 403 })))
  await expect(fetchGraph()).rejects.toBeInstanceOf(ApiError)
})
