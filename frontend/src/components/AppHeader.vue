<script setup>
import { Menu, Coins, Users, Hash, UserCircle, LogOut } from 'lucide-vue-next'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const projectInfo = {
  totalMembers: 24,
  unifiedNumber: '12345678',
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <header class="bg-white border-b border-gray-200 shadow-sm sticky top-0 z-40">
    <div class="flex items-center justify-between px-4 h-12 min-w-0">

      <!-- 左側：Logo 區塊 -->
      <div class="flex items-center gap-2 shrink-0">
        <button class="p-1 rounded hover:bg-gray-100 text-gray-500">
          <Menu :size="20" />
        </button>
        <div class="flex items-center gap-1.5">
          <div class="w-7 h-7 bg-green-500 rounded flex items-center justify-center">
            <Coins :size="16" class="text-white" />
          </div>
          <span class="font-bold text-gray-800 text-base">AcctAssist</span>
        </div>
      </div>

      <!-- 頁面導覽連結 -->
      <nav class="flex items-center gap-1 ml-4 shrink-0">
        <router-link
          to="/"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors"
          :class="route.path === '/'
            ? 'bg-gray-100 text-gray-900 font-medium'
            : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        >
          📋 費用管理
        </router-link>
        <router-link
          to="/roster"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors"
          :class="route.path === '/roster'
            ? 'bg-gray-100 text-gray-900 font-medium'
            : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        >
          👥 員工名冊
        </router-link>
      </nav>

      <!-- 中間：專案 Tag 標籤 -->
      <div class="flex items-center gap-3 text-sm mx-4 shrink-0">
        <div class="flex items-center gap-1.5 bg-gray-100 rounded px-2.5 py-1">
          <Users :size="13" class="text-gray-500" />
          <span class="text-gray-600">專案總人數：</span>
          <span class="font-semibold text-gray-800">{{ projectInfo.totalMembers }} 人</span>
        </div>
        <div class="flex items-center gap-1.5 bg-gray-100 rounded px-2.5 py-1">
          <Hash :size="13" class="text-gray-500" />
          <span class="text-gray-600">統一編號：</span>
          <span class="font-semibold text-gray-800">{{ projectInfo.unifiedNumber }}</span>
        </div>
      </div>

      <!-- 右側：使用者資訊 + 按鈕 -->
      <div class="flex items-center gap-2 shrink-0">
        <div class="flex items-center gap-1.5 text-sm text-gray-600">
          <UserCircle :size="18" class="text-gray-400" />
          <span>{{ authStore.displayName }}</span>
          <span v-if="authStore.employeeId" class="text-xs text-gray-400">({{ authStore.employeeId }})</span>
        </div>
        <button
          @click="handleLogout"
          class="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        >
          <LogOut :size="14" />
          登出
        </button>
      </div>

    </div>
  </header>
</template>
