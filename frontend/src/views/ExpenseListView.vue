<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useExpenseStore } from '../stores/expenseStore'
import FilterPanel from '../components/FilterPanel.vue'
import ExpenseTable from '../components/ExpenseTable.vue'
import Pagination from '../components/Pagination.vue'
import { Download, ChevronDown, Loader2, PackageX, Calendar } from 'lucide-vue-next'
import { fetchWaitingReturns } from '../api/expenseApi'
import WaitingReturnModal from '../components/WaitingReturnModal.vue'

const store = useExpenseStore()
const isExporting = ref(false)

// Dashboard 功能按鈕開關（由根目錄 .env 的 VITE_ 變數控制，預設開啟）
const showDuplicateDetection = import.meta.env.VITE_ENABLE_DUPLICATE_DETECTION !== 'false'
const showWaitingReturnModal = ref(false)
const waitingReturnCount = ref(0)

// ── 匯出下拉選單 ──────────────────────────────────────────────────
const showExportMenu = ref(false)
const exportCustomFrom = ref('')
const exportCustomTo = ref('')

function _padMonth(n) { return String(n).padStart(2, '0') }

function _monthRange(year, month) {
  const lastDay = new Date(year, month, 0).getDate()
  return {
    date_from: `${year}-${_padMonth(month)}-01`,
    date_to:   `${year}-${_padMonth(month)}-${lastDay}`,
  }
}

// 快捷期間選項
const exportPresets = computed(() => {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth() + 1  // 1-based

  const prevMonth = m === 1 ? { y: y - 1, m: 12 } : { y, m: m - 1 }
  const q = Math.ceil(m / 3)
  const qStart = (q - 1) * 3 + 1
  const qEnd = q * 3

  return [
    { label: '本月',   ...(_monthRange(y, m)) },
    { label: '上個月', ...(_monthRange(prevMonth.y, prevMonth.m)) },
    {
      label: `本季（Q${q}）`,
      date_from: `${y}-${_padMonth(qStart)}-01`,
      date_to:   (() => { const d = new Date(y, qEnd, 0); return `${d.getFullYear()}-${_padMonth(d.getMonth()+1)}-${d.getDate()}` })(),
    },
    {
      label: `本年度（${y}）`,
      date_from: `${y}-01-01`,
      date_to:   `${y}-12-31`,
    },
    { label: '全部（不限日期）', date_from: '', date_to: '' },
  ]
})

async function handleExportPreset(preset) {
  showExportMenu.value = false
  await doExport({ date_from: preset.date_from || undefined, date_to: preset.date_to || undefined })
}

async function handleExportCustom() {
  if (!exportCustomFrom.value || !exportCustomTo.value) {
    alert('請填入起始與結束日期')
    return
  }
  showExportMenu.value = false
  await doExport({ date_from: exportCustomFrom.value, date_to: exportCustomTo.value })
}

async function doExport(params) {
  if (isExporting.value) return
  isExporting.value = true
  try {
    await store.downloadExport(params)
  } catch {
    alert('匯出失敗，請確認後端服務是否運行中')
  } finally {
    isExporting.value = false
  }
}

// 點選選單外部時關閉
function onClickOutside(e) {
  if (!e.target.closest('.export-menu-root')) showExportMenu.value = false
}

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
  document.addEventListener('click', onClickOutside)
})
onBeforeUnmount(() => document.removeEventListener('click', onClickOutside))
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 篩選區塊 -->
    <div class="px-4 pt-4">
      <FilterPanel />
    </div>

    <!-- 操作按鈕列 -->
    <div class="px-4 pb-3 flex items-center gap-2">

      <!-- 匯出按鈕（含下拉選單） -->
      <div class="relative export-menu-root">
        <button
          @click.stop="showExportMenu = !showExportMenu"
          :disabled="isExporting"
          class="flex items-center gap-1.5 px-4 py-1.5 bg-blue-500 hover:bg-blue-600 disabled:opacity-60 text-white rounded-full text-sm font-medium transition-colors"
        >
          <Loader2 v-if="isExporting" :size="14" class="animate-spin" />
          <Download v-else :size="14" />
          {{ isExporting ? '匯出中...' : '匯出 CSV' }}
          <ChevronDown v-if="!isExporting" :size="14" :class="showExportMenu ? 'rotate-180' : ''" class="transition-transform" />
        </button>

        <!-- 下拉選單 -->
        <div
          v-if="showExportMenu && !isExporting"
          class="absolute left-0 top-full mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg w-64 py-1"
        >
          <!-- 快捷期間 -->
          <div class="px-3 pt-1.5 pb-0.5 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">快捷期間</div>
          <button
            v-for="preset in exportPresets"
            :key="preset.label"
            @click="handleExportPreset(preset)"
            class="w-full text-left px-4 py-1.5 text-sm text-gray-700 hover:bg-blue-50 hover:text-blue-700 flex items-center gap-2 transition-colors"
          >
            <Calendar :size="13" class="text-gray-400 shrink-0" />
            {{ preset.label }}
            <span v-if="preset.date_from" class="ml-auto text-[10px] text-gray-400">
              {{ preset.date_from.slice(0, 7) }}
              <template v-if="preset.date_from.slice(0, 7) !== preset.date_to.slice(0, 7)"> → {{ preset.date_to.slice(0, 7) }}</template>
            </span>
          </button>

          <!-- 自訂範圍 -->
          <div class="border-t border-gray-100 mt-1 px-3 pt-2 pb-2">
            <div class="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">自訂日期範圍</div>
            <div class="flex items-center gap-1.5 mb-2">
              <input
                v-model="exportCustomFrom"
                type="date"
                class="flex-1 border border-gray-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                placeholder="起始"
              />
              <span class="text-gray-400 text-xs">→</span>
              <input
                v-model="exportCustomTo"
                type="date"
                class="flex-1 border border-gray-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                placeholder="結束"
              />
            </div>
            <button
              @click="handleExportCustom"
              class="w-full py-1.5 bg-blue-500 hover:bg-blue-600 text-white text-xs rounded font-medium transition-colors flex items-center justify-center gap-1.5"
            >
              <Download :size="12" />
              下載此區間 CSV
            </button>
          </div>
        </div>
      </div>

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

    <!-- 待退貨管理 Modal -->
    <WaitingReturnModal
      v-if="showWaitingReturnModal"
      @close="showWaitingReturnModal = false"
      @count-changed="() => { loadWaitingReturnCount(); store.fetchExpenses() }"
    />
  </div>
</template>
