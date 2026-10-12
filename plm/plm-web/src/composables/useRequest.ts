import { ref } from 'vue'

export function useRequest<TArgs extends unknown[], TResult>(requestFn: (...args: TArgs) => Promise<TResult>) {
  const loading = ref(false)
  const error = ref<string>('')

  async function run(...args: TArgs) {
    loading.value = true
    error.value = ''
    try {
      return await requestFn(...args)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '请求失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    error,
    run
  }
}
