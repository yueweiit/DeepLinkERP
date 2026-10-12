import type { App } from 'vue'
import { debounceDirective } from './debounce'
import { permissionDirective } from './permission'

export function registerDirectives(app: App) {
  app.directive('permission', permissionDirective)
  app.directive('debounce', debounceDirective)
}
