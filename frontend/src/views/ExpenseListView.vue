<script setup>
import { ref, onMounted } from 'vue'
import { useExpenseStore } from '../stores/expenseStore'
import FilterPanel from '../components/FilterPanel.vue'
import ExpenseTable from '../components/ExpenseTable.vue'
import Pagination from '../components/Pagination.vue'
import { Plus, Download, ChevronDown, Loader2, Zap, Settings, PackageX, TriangleAlert } from 'lucide-vue-next'
import { processPendingNow, fetchWaitingReturns } from '../api/expenseApi'
import SchedulerConfigModal from '../components/SchedulerConfigModal.vue'
import WaitingReturnModal from '../components/WaitingReturnModal.vue'

const store = useExpenseStore()
const isExporting = ref(false)
const isProcessing = ref(false)
const processResult = ref(null) // { type: 'success' | 'error', message: string }

// Dashboard 功能按鈕開關（由根目錄 .env 的 VITE_ 變數控制，預設開啟）
const showProcessPending = import.meta.env.VITE_ENABLE_PROCESS_PENDING !== 'false'
const showSchedulerConfig = import.meta.env.VITE_ENABLE_SCHEDULER_CONFIG !== 'false'
const showDuplicateDetection = import.meta.env.VITE_ENABLE_DUPLICATE_DETECTION !== 'false'
const showSchedulerModal = ref(false)
const showWaitingReturnModal = ref(false)
const waitingReturnCount = ref(0)

async function loadWaitingReturnCount() {
  try {
    const res = await fetchWaitingReturns()
    waitingReturnCount.value = res.data?.data?.total ?? 0
  } catch {
    waitingReturnCount.value = 0
  }
}

onMounted(() => {
  store.fetchExpenses()
  loadWaitingReturnCount()
})

async function handleExport() {
  if (isExporting.value) return
  isExporting.value = true
  try {
    await store.downloadExport()
  } catch {
    alert('匯出失敗，請確認後端服務是否運行中')
  } finally {
    isExporting.value = false
  }
}

async function handleProcessPending() {
  if (isProcessing.value) return
  isProcessing.value = true
  processResult.value = null
  try {
    const res = await processPendingNow()
    processResult.value = {
      type: 'success',
      message: res.data?.message || '批次處理已開始，請稍後重新整理',
    }
    // 5 秒後自動重整列表，讓新建立的 Expense 出現
    setTimeout(() => {
      store.fetchExpenses()
      processResult.value = null
    }, 5000)
  } catch {
    processResult.value = {
      type: 'error',
      message: '觸發失敗，請確認後端服務是否運行中',
    }
    setTimeout(() => { processResult.value = null }, 4000)
  } finally {
    isProcessing.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 篩選區塊 -->
    <div class="px-4 pt-4">
      <FilterPanel />
    </div>

    <!-- 操作按鈕列 -->
    <div class="px-4 pb-3 flex items-center gap-2">
      <button
        @click="store.openCreateModal()"
        class="flex items-center gap-1.5 px-3 py-1.5 border border-gray-400 rounded-full text-sm text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <Plus :size="14" />
        新增一筆費用
      </button>

      <button
        @click="handleExport"
        :disabled="isExporting"
        class="flex items-center gap-1.5 px-4 py-1.5 bg-blue-500 hover:bg-blue-600 disabled:opacity-60 text-white rounded-full text-sm font-medium transition-colors"
      >
        <Loader2 v-if="isExporting" :size="14" class="animate-spin" />
        <Download v-else :size="14" />
        {{ isExporting ? '匯出中...' : '匯出' }}
        <ChevronDown v-if="!isExporting" :size="14" />
      </button>

      <button
        v-if="showProcessPending"
        @click="handleProcessPending"
        :disabled="isProcessing"
        class="flex items-center gap-1.5 px-4 py-1.5 bg-orange-500 hover:bg-orange-600 disabled:opacity-60 text-white rounded-full text-sm font-medium transition-colors"
      >
        <Loader2 v-if="isProcessing" :size="14" class="animate-spin" />
        <Zap v-else :size="14" />
        {{ isProcessing ? '處理中...' : '立即處理 Pending' }}
      </button>

      <button
        v-if="showSchedulerConfig"
        @click="showSchedulerModal = true"
        class="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 hover:border-orange-400 hover:text-orange-500 text-gray-500 rounded-full text-sm transition-colors"
        title="排程批次設定"
      >
        <Settings :size="14" />
        排程設定
      </button>

      <button
        @click="showWaitingReturnModal = true"
        class="relative flex items-center gap-1.5 px-3 py-1.5 border border-purple-300 hover:bg-purple-50 text-purple-600 rounded-full text-sm font-medium transition-colors"
        title="待退貨補件管理"
      >
        <PackageX :size="14" />
        待退貨
        <span
          v-if="waitingReturnCount > 0"
          class="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] flex items-center justify-center bg-purple-500 text-white text-[10px] font-bold rounded-full px-1"
        >{{ waitingReturnCount }}</span>
      </button>

      <button
        v-if="showDuplicateDetection"
        @click="store.toggleDuplicateFilter()"
        :class="[
          'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium transition-colors',
          store.hasDuplicateFilter
            ? 'bg-red-500 text-white border border-red-500'
            : 'border border-red-300 hover:bg-red-50 text-red-600'
        ]"
        title="篩選疑似重複憑證"
      >
        <TriangleAlert :size="14" />
        疑似重複
      </button>
    </div>

    <!-- 批次處理結果提示 -->
    <div v-if="processResult" class="px-4 pb-2">
      <div
        :class="[
          'text-sm rounded px-3 py-2 flex items-center justify-between',
          processResult.type === 'success'
            ? 'bg-green-50 border border-green-200 text-green-700'
            : 'bg-red-50 border border-red-200 text-red-600',
        ]"
      >
        <span>{{ processResult.message }}</span>
        <button
          @click="processResult = null"
          class="ml-4 opacity-60 hover:opacity-100 text-lg leading-none"
        >×</button>
      </div>
    </div>

    <!-- 載入中提示 -->
    <div v-if="store.isLoading" class="px-4 pb-2 flex items-center gap-2 text-sm text-gray-500">
      <Loader2 :size="16" class="animate-spin" />
      載入中...
    </div>

    <!-- API 錯誤提示 -->
    <div v-if="store.error && !store.isLoading" class="px-4 pb-2">
      <div class="bg-red-50 border border-red-200 text-red-600 text-sm rounded px-3 py-2 flex items-center justify-between">
        <span>{{ store.error }}</span>
        <button
          @click="store.fetchExpenses()"
          class="underline text-red-500 hover:text-red-700 ml-4"
        >重試</button>
      </div>
    </div>

    <!-- 資料表格 + 分頁 -->
    <div class="px-4 pb-6">
      <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <ExpenseTable />
        <Pagination />
      </div>
    </div>

    <!-- 排程設定 Modal -->
    <SchedulerConfigModal
      v-if="showSchedulerModal"
      @close="showSchedulerModal = false"
    />

    <!-- 待退貨管理 Modal -->
    <WaitingReturnModal
      v-if="showWaitingReturnModal"
      @close="showWaitingReturnModal = false"
      @count-changed="() => { loadWaitingReturnCount(); store.fetchExpenses() }"
    />
  </div>
</template>
