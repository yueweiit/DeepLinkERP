import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'

import { getProfileByToken, loginByPassword, loginByDingTalkCode, logout as logoutApi } from '@/api/modules/auth'
import type { UserProfile } from '@/types/common'
import { registerSessionInvalidation } from '@/api/request'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('plm_token') || '')
  const profile = ref<UserProfile | null>(null)
  const permissions = ref<string[]>([])

  const isLoggedIn = computed(() => Boolean(token.value))

  function clearSession(expectedToken?: string | null) {
    if (expectedToken !== undefined && token.value !== (expectedToken || '')) return
    token.value = ''
    profile.value = null
    permissions.value = []
    localStorage.removeItem('plm_token')
  }
  onScopeDispose(registerSessionInvalidation(clearSession))

  function setSession(payload: { token: string; profile: UserProfile; permissions: string[] }) {
    token.value = payload.token
    profile.value = payload.profile
    permissions.value = payload.permissions
    localStorage.setItem('plm_token', payload.token)
  }

  async function login(payload: { username: string; password: string }) {
    const session = await loginByPassword(payload)
    setSession(session)
    return session
  }

  async function loginDingTalk(code: string) {
    const session = await loginByDingTalkCode(code)
    setSession(session)
    return session
  }

  async function restore() {
    if (!token.value) {
      return
    }

    const restoringToken = token.value
    try {
      const session = await getProfileByToken(restoringToken)
      if (token.value !== restoringToken) return
      profile.value = session.profile
      permissions.value = session.permissions
    } catch (error) {
      clearSession(restoringToken)
      throw error
    }
  }

  async function logout() {
    const loggingOutToken = token.value
    try {
      if (token.value) {
        await logoutApi()
      }
    } finally {
      clearSession(loggingOutToken)
    }
  }

  function hasPermission(permission?: string) {
    if (!permission) {
      return true
    }
    return permissions.value.includes('*') || permissions.value.includes(permission)
  }

  return {
    token,
    profile,
    permissions,
    isLoggedIn,
    login,
    loginDingTalk,
    restore,
    logout,
    clearSession,
    hasPermission
  }
})
