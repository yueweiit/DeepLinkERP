import { computed, ref } from 'vue'

export function usePagination(defaultPageSize = 10) {
  const currentPage = ref(1)
  const pageSize = ref(defaultPageSize)

  function resetPage() {
    currentPage.value = 1
  }

  function getPagedRows<T>(rows: T[]) {
    const start = (currentPage.value - 1) * pageSize.value
    return rows.slice(start, start + pageSize.value)
  }

  const offset = computed(() => (currentPage.value - 1) * pageSize.value)

  return {
    currentPage,
    pageSize,
    offset,
    resetPage,
    getPagedRows
  }
}
