import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin } from '../api/authApi'

const TOKEN_KEY       = 'acctassist_token'
const USERNAME_KEY    = 'acctassist_username'
const DISPLAY_NAME_KEY = 'acctassist_display_name'
const EMPLOYEE_ID_KEY  = 'acctassist_employee_id'

export const useAuthStore = defineStore('auth', () => {
  const token       = ref(localStorage.getItem(TOKEN_KEY) || '')
  const username    = ref(localStorage.getItem(USERNAME_KEY) || '')
  const displayName = ref(localStorage.getItem(DISPLAY_NAME_KEY) || '')
  const employeeId  = ref(localStorage.getItem(EMPLOYEE_ID_KEY) || '')

  const isLoggedIn = computed(() => !!token.value)

  async function login(usernameVal, password) {
    const res = await apiLogin(usernameVal, password)
    const { access_token, display_name, employee_id } = res.data.data

    token.value       = access_token
    username.value    = usernameVal
    displayName.value = display_name || usernameVal
    employeeId.value  = employee_id || ''

    localStorage.setItem(TOKEN_KEY,        access_token)
    localStorage.setItem(USERNAME_KEY,     usernameVal)
    localStorage.setItem(DISPLAY_NAME_KEY, display_name || usernameVal)
    localStorage.setItem(EMPLOYEE_ID_KEY,  employee_id || '')
  }

  function logout() {
    token.value       = ''
    username.value    = ''
    displayName.value = ''
    employeeId.value  = ''
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USERNAME_KEY)
    localStorage.removeItem(DISPLAY_NAME_KEY)
    localStorage.removeItem(EMPLOYEE_ID_KEY)
  }

  return { token, username, displayName, employeeId, isLoggedIn, login, logout }
})
