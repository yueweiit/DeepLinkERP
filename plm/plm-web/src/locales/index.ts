import type { App } from 'vue'
import type { ComponentCustomProperties } from 'vue'

import zhCNCommon from './zh-CN/common'
import zhCNCustomer from './zh-CN/customer'
import zhCNProduct from './zh-CN/product'

const messages = {
  ...zhCNCommon,
  ...zhCNCustomer,
  ...zhCNProduct
} as Record<string, string>

export function t(key: string, params?: Record<string, string | number>): string {
  const template = messages[key] || key
  if (!params) {
    return template
  }

  return Object.entries(params).reduce((content, [paramKey, value]) => {
    return content.replace(new RegExp(`{${paramKey}}`, 'g'), String(value))
  }, template)
}

export function createLocalePlugin() {
  return {
    install(app: App) {
      app.config.globalProperties.$t = t
      app.provide('t', t)
    }
  }
}

declare module '@vue/runtime-core' {
  interface ComponentCustomProperties {
    $t: typeof t
  }
}
