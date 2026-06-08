<script setup>
import { onMounted } from 'vue'
import AppHeader from './components/AppHeader.vue'
import AuditModal from './components/AuditModal.vue'
import { useAuthStore } from './stores/authStore'

const authStore = useAuthStore()
onMounted(() => {
  authStore.fetchProjectInfo()
})
</script>

<template>
  <div id="app" class="min-h-screen bg-gray-50 flex flex-col">
    <!-- 頂部導覽列（固定） -->
    <AppHeader />

    <!-- 主要內容區 -->
    <main class="flex-1">
      <router-view />
    </main>

    <!-- 審核 Modal（Teleport 掛載到 body，全域可用） -->
    <AuditModal />
  </div>
</template>
