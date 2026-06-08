import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin, getProjectInfo } from '../api/authApi'
import { getRosterList } from '../api/rosterApi'

const TOKEN_KEY          = 'acctassist_token'
const USERNAME_KEY       = 'acctassist_username'
const DISPLAY_NAME_KEY   = 'acctassist_display_name'
const EMPLOYEE_ID_KEY    = 'acctassist_employee_id'
const COMPANY_TAX_ID_KEY = 'acctassist_company_tax_id'
const TOTAL_MEMBERS_KEY  = 'acctassist_total_members'

export const useAuthStore = defineStore('auth', () => {
  const token         = ref(localStorage.getItem(TOKEN_KEY) || '')
  const username      = ref(localStorage.getItem(USERNAME_KEY) || '')
  const displayName   = ref(localStorage.getItem(DISPLAY_NAME_KEY) || '')
  const employeeId    = ref(localStorage.getItem(EMPLOYEE_ID_KEY) || '')
  const companyTaxId  = ref(localStorage.getItem(COMPANY_TAX_ID_KEY) || '')
  const totalMembers  = ref(Number(localStorage.getItem(TOTAL_MEMBERS_KEY)) || 0)

  const isLoggedIn = computed(() => !!token.value)

  async function login(usernameVal, password) {
    const res = await apiLogin(usernameVal, password)
    const { access_token, display_name, employee_id, company_tax_id } = res.data.data

    token.value        = access_token
    username.value     = usernameVal
    displayName.value  = display_name || usernameVal
    employeeId.value   = employee_id || ''
    companyTaxId.value = company_tax_id || ''

    localStorage.setItem(TOKEN_KEY,          access_token)
    localStorage.setItem(USERNAME_KEY,       usernameVal)
    localStorage.setItem(DISPLAY_NAME_KEY,   display_name || usernameVal)
    localStorage.setItem(EMPLOYEE_ID_KEY,    employee_id || '')
    localStorage.setItem(COMPANY_TAX_ID_KEY, company_tax_id || '')

    // 登入後抓名冊總人數（只取第 1 筆，用 total_elements）
    try {
      const rosterRes = await getRosterList({ page: 0, size: 1 })
      const count = rosterRes.data?.data?.total_elements ?? 0
      totalMembers.value = count
      localStorage.setItem(TOTAL_MEMBERS_KEY, String(count))
    } catch {
      totalMembers.value = 0
    }
  }

  function logout() {
    token.value        = ''
    username.value     = ''
    displayName.value  = ''
    employeeId.value   = ''
    companyTaxId.value = ''
    totalMembers.value = 0
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USERNAME_KEY)
    localStorage.removeItem(DISPLAY_NAME_KEY)
    localStorage.removeItem(EMPLOYEE_ID_KEY)
    localStorage.removeItem(COMPANY_TAX_ID_KEY)
    localStorage.removeItem(TOTAL_MEMBERS_KEY)
  }

  async function fetchProjectInfo() {
    if (!token.value) return
    try {
      const res = await getProjectInfo()
      const taxId = res.data?.data?.company_tax_id ?? ''
      companyTaxId.value = taxId
      localStorage.setItem(COMPANY_TAX_ID_KEY, taxId)
    } catch {
      // 靜默失敗，沿用 localStorage 快取值
    }
  }

  return { token, username, displayName, employeeId, companyTaxId, totalMembers, isLoggedIn, login, logout, fetchProjectInfo }
})
