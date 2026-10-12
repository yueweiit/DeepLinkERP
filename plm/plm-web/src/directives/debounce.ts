import type { Directive } from 'vue'

type DebounceElement = HTMLElement & {
  __plmClickHandler__?: EventListener
}

export const debounceDirective: Directive<DebounceElement, number> = {
  mounted(el, binding) {
    const delay = binding.value || 400
    let timer = 0

    const handler = (event: Event) => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        el.dispatchEvent(new CustomEvent('plm-debounced-click', { detail: event }))
      }, delay)
    }

    el.__plmClickHandler__ = handler
    el.addEventListener('click', handler)
  },
  unmounted(el) {
    if (el.__plmClickHandler__) {
      el.removeEventListener('click', el.__plmClickHandler__)
    }
  }
}
