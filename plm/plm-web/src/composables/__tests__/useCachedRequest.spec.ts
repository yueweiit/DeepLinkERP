import { effectScope } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useCachedRequest } from '../useCachedRequest'

afterEach(() => vi.restoreAllMocks())

describe('useCachedRequest', () => {
  it('does not revive cached results when a pending response arrives after logout/unmount', async () => {
    let finish!: (value: string) => void
    const scope = effectScope()
    const state = scope.run(() => useCachedRequest(() => new Promise<string>((resolve) => { finish = resolve })))!
    const pending = state.execute('private page')
    scope.stop()
    finish('old user result'); await pending
    expect(state.data.value).toBeUndefined()
  })
  it('forces a new request after an import and prevents an older request poisoning its cache', async () => {
    let finishOld!: (value: string) => void
    let finishNew!: (value: string) => void
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<string>((resolve) => { finishOld = resolve }))
      .mockImplementationOnce(() => new Promise<string>((resolve) => { finishNew = resolve }))
    const scope = effectScope()
    const state = scope.run(() => useCachedRequest(fetcher))!
    const old = state.execute('same query')
    const fresh = state.execute('same query', true)
    expect(fetcher).toHaveBeenCalledTimes(2)
    finishNew('after import'); await fresh
    finishOld('before import'); await old
    await state.execute('same query')
    expect(state.data.value).toBe('after import')
    expect(fetcher).toHaveBeenCalledTimes(2)
    scope.stop()
  })
  it('shows a fresh cached page without another request and refreshes stale data in place', async () => {
    const clock = vi.spyOn(Date, 'now').mockReturnValue(1000)
    const fetcher = vi.fn().mockResolvedValueOnce(['initial']).mockResolvedValueOnce(['new'])
    const scope = effectScope()
    const state = scope.run(() => useCachedRequest(fetcher))!
    await state.execute({ page: 2 })
    clock.mockReturnValue(60_999)
    await state.execute({ page: 2 })
    expect(fetcher).toHaveBeenCalledTimes(1)
    clock.mockReturnValue(61_000)
    const pending = state.execute({ page: 2 })
    expect(state.data.value).toEqual(['initial'])
    expect(state.loading.value).toBe(false)
    await pending
    expect(state.data.value).toEqual(['new'])
    expect(fetcher).toHaveBeenCalledTimes(2)
    scope.stop()
  })

  it('coalesces identical in-flight requests and ignores old responses', async () => {
    let finishOld!: (value: string) => void
    let finishNew!: (value: string) => void
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<string>((resolve) => { finishOld = resolve }))
      .mockImplementationOnce(() => new Promise<string>((resolve) => { finishNew = resolve }))
    const scope = effectScope()
    const state = scope.run(() => useCachedRequest(fetcher))!
    const old = state.execute('old')
    const duplicate = state.execute('old')
    expect(fetcher).toHaveBeenCalledTimes(1)
    state.invalidate()
    const latest = state.execute('new')
    finishNew('new response'); await latest
    finishOld('old response'); await Promise.all([old, duplicate])
    expect(state.data.value).toBe('new response')
    scope.stop()
  })

  it('invalidates pending responses while typing and clears caches when disposed', async () => {
    let resolve!: (value: string) => void
    const fetcher = vi.fn().mockImplementation(() => new Promise<string>((done) => { resolve = done }))
    const scope = effectScope()
    const state = scope.run(() => useCachedRequest(fetcher))!
    const pending = state.execute('a')
    state.invalidate(); resolve('stale'); await pending
    expect(state.data.value).toBeUndefined()
    scope.stop()
    const newScope = effectScope()
    const freshState = newScope.run(() => useCachedRequest(fetcher))!
    const next = freshState.execute('a')
    expect(fetcher).toHaveBeenCalledTimes(2)
    resolve('after dispose'); await next
    expect(state.data.value).toBeUndefined()
    newScope.stop()
  })
})
