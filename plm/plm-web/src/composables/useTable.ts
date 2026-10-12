import { computed, reactive, type Ref } from 'vue'
import { usePagination } from './usePagination'

export function useTable<T extends object>(
  sourceRows: Ref<T[]>,
  searchableKeys: Array<keyof T>,
  extraFilter?: (row: T, filters: Record<string, unknown>) => boolean
) {
  const query = reactive<Record<string, unknown>>({
    keyword: ''
  })
  const pagination = usePagination()

  const filteredRows = computed(() => {
    const keyword = String(query.keyword || '').trim().toLowerCase()

    return sourceRows.value.filter((row) => {
      const keywordMatched =
        !keyword ||
        searchableKeys.some((key) =>
          String(row[key] ?? '')
            .toLowerCase()
            .includes(keyword)
        )

      if (!keywordMatched) {
        return false
      }

      return extraFilter ? extraFilter(row, query) : true
    })
  })

  const pagedRows = computed(() => pagination.getPagedRows(filteredRows.value))

  function setQuery(patch: Record<string, unknown>) {
    Object.assign(query, patch)
    pagination.resetPage()
  }

  function resetQuery(defaults: Record<string, unknown> = { keyword: '' }) {
    Object.keys(query).forEach((key) => delete query[key])
    Object.assign(query, defaults)
    pagination.resetPage()
  }

  return {
    query,
    filteredRows,
    pagedRows,
    currentPage: pagination.currentPage,
    pageSize: pagination.pageSize,
    setQuery,
    resetQuery
  }
}
