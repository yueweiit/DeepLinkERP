import axios, { type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: `${import.meta.env.VITE_API_BASE_URL || ''}/api/v1`,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

let sessionInvalidation: ((expiredToken: string | null) => void) | undefined

/** The store owns session state; this layer never imports Pinia or creates a login flow. */
export function registerSessionInvalidation(handler: (expiredToken: string | null) => void) {
  sessionInvalidation = handler
  return () => { if (sessionInvalidation === handler) sessionInvalidation = undefined }
}

function createRequestId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function redirectToLoginOnUnauthorized(config?: InternalAxiosRequestConfig) {
  const authorization = config?.headers?.get?.('Authorization') ?? config?.headers?.Authorization
  const sentToken = typeof authorization === 'string' ? /^Bearer\s+(.+)$/i.exec(authorization)?.[1] ?? null : null
  const currentToken = localStorage.getItem('plm_token')
  if (sentToken !== currentToken) return // A late 401 must not invalidate a later login.
  sessionInvalidation?.(currentToken)
  localStorage.removeItem('plm_token')
  if (window.location.hash.startsWith('#/login')) {
    return
  }
  const current = window.location.hash.replace(/^#/, '') || '/'
  window.location.hash = `/login?redirect=${encodeURIComponent(current)}`
}

export function prepareRequestContentType(config: InternalAxiosRequestConfig) {
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    config.headers.delete('Content-Type')
  }
  return config
}

request.interceptors.request.use((config) => {
  prepareRequestContentType(config)
  const token = localStorage.getItem('plm_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  config.headers['X-Request-Id'] = createRequestId()
  return config
})

request.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 || error.response?.data?.code === 40101) {
      redirectToLoginOnUnauthorized(error.config ?? error.response?.config)
    }
    ElMessage.error(error.response?.data?.message || '网络请求失败')
    return Promise.reject(error)
  }
)

export function mockResolve<T>(factory: () => T, delay = 180): Promise<T> {
  return new Promise((resolve, reject) => {
    window.setTimeout(() => {
      try {
        resolve(factory())
      } catch (error) {
        reject(error)
      }
    }, delay)
  })
}

export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  requestId?: string
  timestamp?: string
}

export interface PageResponse<T> {
  content: T[]
  page: number
  size: number
  totalElements: number
  totalPages: number
}

export function unwrapResponse<T>(response: AxiosResponse<ApiResponse<T>>): T {
  const body = response.data
  if (body.code !== 0) {
    if (body.code === 40101) {
      redirectToLoginOnUnauthorized(response.config)
    }
    throw new Error(body.message || '接口请求失败')
  }
  return body.data
}

export function unwrapPage<T>(response: AxiosResponse<ApiResponse<PageResponse<T>>>): PageResponse<T> {
  return unwrapResponse(response)
}

export default request
