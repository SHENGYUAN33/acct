<template>
  <div class="min-h-screen bg-gray-100 flex items-center justify-center">
    <div class="bg-white rounded-2xl shadow-lg p-8 w-full max-w-sm">
      <h1 class="text-2xl font-bold text-gray-800 mb-2 text-center">AcctAssist</h1>
      <p class="text-sm text-gray-500 text-center mb-6">報帳審核管理系統</p>

      <!-- 登入表單 -->
      <form v-if="mode === 'login'" @submit.prevent="handleLogin" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">帳號</label>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            required
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="請輸入帳號"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">密碼</label>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="請輸入密碼"
          />
        </div>

        <p v-if="errorMsg" class="text-sm text-red-500">{{ errorMsg }}</p>

        <button
          type="submit"
          :disabled="isLoading"
          class="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2 rounded-lg text-sm transition-colors"
        >
          {{ isLoading ? '登入中…' : '登入' }}
        </button>

        <p class="text-center text-sm text-gray-500">
          還沒有帳號？
          <button type="button" @click="switchMode('register')" class="text-blue-600 hover:underline">
            建立帳號
          </button>
        </p>
      </form>

      <!-- 建立帳號表單 -->
      <form v-else @submit.prevent="handleRegister" class="space-y-4">
        <!-- 姓名 -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            姓名 <span class="text-red-500">*</span>
          </label>
          <input
            v-model="displayName"
            type="text"
            required
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="請輸入真實姓名"
          />
        </div>
        <!-- 工號 -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            工號 <span class="text-red-500">*</span>
          </label>
          <input
            v-model="employeeId"
            type="text"
            required
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="請輸入工號（唯一）"
          />
        </div>
        <!-- 帳號 -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            登入帳號 <span class="text-red-500">*</span>
          </label>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            required
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="設定登入用帳號"
          />
        </div>
        <!-- 密碼 -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            密碼 <span class="text-red-500">*</span>
          </label>
          <input
            v-model="password"
            type="password"
            autocomplete="new-password"
            required
            class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="設定密碼"
          />
        </div>

        <p v-if="errorMsg" class="text-sm text-red-500">{{ errorMsg }}</p>
        <p v-if="successMsg" class="text-sm text-green-600">{{ successMsg }}</p>

        <button
          type="submit"
          :disabled="isLoading"
          class="w-full bg-green-600 hover:bg-green-700 disabled:bg-green-400 text-white font-medium py-2 rounded-lg text-sm transition-colors"
        >
          {{ isLoading ? '建立中…' : '建立帳號' }}
        </button>

        <p class="text-center text-sm text-gray-500">
          已有帳號？
          <button type="button" @click="switchMode('login')" class="text-blue-600 hover:underline">
            返回登入
          </button>
        </p>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'
import { register as apiRegister } from '../api/authApi'

const router = useRouter()
const authStore = useAuthStore()

const mode = ref('login')       // 'login' | 'register'
const username    = ref('')
const password    = ref('')
const displayName = ref('')
const employeeId  = ref('')
const isLoading   = ref(false)
const errorMsg    = ref('')
const successMsg  = ref('')

function switchMode(target) {
  mode.value        = target
  username.value    = ''
  password.value    = ''
  displayName.value = ''
  employeeId.value  = ''
  errorMsg.value    = ''
  successMsg.value  = ''
}

async function handleLogin() {
  errorMsg.value = ''
  isLoading.value = true
  try {
    await authStore.login(username.value, password.value)
    router.push('/')
  } catch (err) {
    const detail = err.response?.data?.detail
    errorMsg.value = detail || '登入失敗，請確認帳號密碼'
  } finally {
    isLoading.value = false
  }
}

async function handleRegister() {
  errorMsg.value   = ''
  successMsg.value = ''
  isLoading.value  = true
  try {
    await apiRegister(username.value, password.value, displayName.value, employeeId.value)
    successMsg.value = `帳號「${displayName.value}」建立成功！請返回登入。`
    password.value   = ''
  } catch (err) {
    const detail = err.response?.data?.detail
    errorMsg.value = detail || '建立失敗，請稍後再試'
  } finally {
    isLoading.value = false
  }
}
</script>
