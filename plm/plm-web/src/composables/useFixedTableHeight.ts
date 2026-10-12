import { nextTick, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export interface FixedTableHeightOptions {
  viewportHeight: number
  reservedHeight: number
  minHeight?: number
  maxHeight?: number
}

export function resolveFixedTableHeight({
  viewportHeight,
  reservedHeight,
  minHeight = 320,
  maxHeight = 760
}: FixedTableHeightOptions) {
  return Math.min(maxHeight, Math.max(minHeight, viewportHeight - reservedHeight))
}

export function useFixedTableHeight(containerRef: Ref<HTMLElement | null>, bottomOffset = 24) {
  const tableHeight = ref(320)

  function refresh() {
    const top = containerRef.value?.getBoundingClientRect().top ?? 0
    tableHeight.value = resolveFixedTableHeight({
      viewportHeight: window.innerHeight,
      reservedHeight: top + bottomOffset
    })
  }

  async function refreshAfterRender() {
    await nextTick()
    refresh()
  }

  onMounted(() => {
    refresh()
    window.addEventListener('resize', refresh)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', refresh)
  })

  return { tableHeight, refresh, refreshAfterRender }
}
