import type { Directive } from 'vue'
import { useUserStore } from '@/stores/user'

export const permissionDirective: Directive<HTMLElement, string> = {
  mounted(el, binding) {
    const store = useUserStore()
    if (binding.value && !store.hasPermission(binding.value)) {
      el.style.display = 'none'
    }
  }
}
