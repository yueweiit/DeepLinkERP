import { onScopeDispose, ref, shallowRef } from 'vue'

/** A small, session/component-scoped cache. Old requests never replace the active query. */
export function useCachedRequest<T, Q>(fetcher: (query: Q) => Promise<T>, ttl = 60_000) {
  const data = shallowRef<T>()
  const loading = ref(false)
  const error = ref('')
  const hasCurrentData = ref(false)
  const cache = new Map<string, { value: T; fetchedAt: number }>()
  const pending = new Map<string, Promise<T>>()
  let generation = 0
  let dataKey: string | undefined
  let disposed = false

  function invalidate() {
    generation++
    loading.value = false
  }

  async function execute(query: Q, force = false) {
    if (disposed) return
    const key = JSON.stringify(query)
    const current = ++generation
    const cached = cache.get(key)
    error.value = ''
    if (cached) { data.value = cached.value; dataKey = key }
    // Preserve pagination metadata while a new page loads; callers can hide unrelated rows.
    hasCurrentData.value = dataKey === key
    if (!force && cached && Date.now() - cached.fetchedAt < ttl) {
      loading.value = false
      return
    }
    // Keep stale results visible while refreshing in the background.
    loading.value = !cached
    let task = force ? undefined : pending.get(key)
    if (!task) {
      task = fetcher(query)
      pending.set(key, task)
    }
    try {
      const value = await task
      if (disposed) return
      if (pending.get(key) === task) {
        cache.delete(key)
        cache.set(key, { value, fetchedAt: Date.now() })
        if (cache.size > 10) cache.delete(cache.keys().next().value!)
      }
      if (current === generation) {
        data.value = value; dataKey = key; hasCurrentData.value = true
      }
    } catch {
      if (current === generation) error.value = '加载失败，请重试'
    } finally {
      if (pending.get(key) === task) pending.delete(key)
      if (current === generation) loading.value = false
    }
  }

  function clear() {
    invalidate()
    cache.clear()
    pending.clear()
  }
  onScopeDispose(() => { disposed = true; clear(); data.value = undefined; hasCurrentData.value = false; pending.clear() })
  return { data, loading, error, hasCurrentData, execute, invalidate, clear }
}
