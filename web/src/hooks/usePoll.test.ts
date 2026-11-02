import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { parseHouse } from '../data/parse'
import { usePoll } from './usePoll'

const URL = 'https://example.test/house.json'
const INTERVAL = 20_000
const snapshot = (iso: string) => ({ generated_at: iso, mode: 'live', races: [] })
const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('usePoll', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('makes no request while disabled', async () => {
    renderHook(() => usePoll(URL, parseHouse, INTERVAL, 1000, { enabled: false }))
    await advance(INTERVAL * 3)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('starts when enabled, stops when disabled, keeps the last snapshot', async () => {
    fetchMock.mockImplementation(async () => ok(snapshot('2026-11-04T02:30:00Z')))
    const { result, rerender } = renderHook(({ enabled }) => usePoll(URL, parseHouse, INTERVAL, 1000, { enabled }), {
      initialProps: { enabled: true },
    })
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await advance(INTERVAL)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    expect(result.current.settled).toBe(true)

    rerender({ enabled: false })
    await advance(INTERVAL * 3)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.current.data?.generatedAt.toISOString()).toBe('2026-11-04T02:30:00.000Z')
    expect(result.current.settled).toBe(false)

    rerender({ enabled: true })
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(result.current.settled).toBe(true)
  })

  it('a 404 with missingOk is neither a snapshot nor an error, and polling continues', async () => {
    fetchMock.mockImplementation(async () => new Response('<Error/>', { status: 404 }))
    const { result } = renderHook(() => usePoll(URL, parseHouse, INTERVAL, 1000, { missingOk: true }))
    await flush()
    expect(result.current).toEqual({ data: null, lastError: null, settled: true })
    await advance(INTERVAL)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('the file appearing later is picked up without a reload', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 404 }))
    fetchMock.mockResolvedValueOnce(ok(snapshot('2026-11-04T02:30:00Z')))
    const { result } = renderHook(() => usePoll(URL, parseHouse, INTERVAL, 1000, { missingOk: true }))
    await flush()
    expect(result.current.data).toBeNull()
    await advance(INTERVAL)
    expect(result.current.data).not.toBeNull()
  })

  it('a 404 after a snapshot keeps the numbers, with no error', async () => {
    fetchMock.mockResolvedValueOnce(ok(snapshot('2026-11-04T02:30:00Z')))
    fetchMock.mockResolvedValueOnce(new Response('', { status: 404 }))
    const { result } = renderHook(() => usePoll(URL, parseHouse, INTERVAL, 1000, { missingOk: true }))
    await flush()
    await advance(INTERVAL)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.current.data).not.toBeNull()
    expect(result.current.lastError).toBeNull()
  })

  it('a 404 without missingOk is an error (summary.json must exist)', async () => {
    fetchMock.mockImplementation(async () => new Response('', { status: 404 }))
    const { result } = renderHook(() => usePoll(URL, parseHouse, INTERVAL, 1000))
    await flush()
    expect(result.current.lastError).toBe('HTTP 404')
  })

  it('a 5xx is an error even with missingOk', async () => {
    fetchMock.mockImplementation(async () => new Response('', { status: 503 }))
    const { result } = renderHook(() => usePoll(URL, parseHouse, INTERVAL, 1000, { missingOk: true }))
    await flush()
    expect(result.current.lastError).toBe('HTTP 503')
  })

  it('an older snapshot never replaces a newer one', async () => {
    fetchMock.mockResolvedValueOnce(ok(snapshot('2026-11-04T02:30:00Z')))
    fetchMock.mockResolvedValueOnce(ok(snapshot('2026-11-04T02:29:00Z')))
    const { result } = renderHook(() => usePoll(URL, parseHouse, INTERVAL, 1000))
    await flush()
    await advance(INTERVAL)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.current.data?.generatedAt.toISOString()).toBe('2026-11-04T02:30:00.000Z')
  })
})
