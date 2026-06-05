<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { SlidersHorizontal, Search, X } from 'lucide-vue-next'
import { useExpenseStore } from '../stores/expenseStore'
import { fetchDepartments } from '../api/configApi'

const store = useExpenseStore()

// ── 選項定義 ────────────────────────────────────────────────────

const statusOptions = [
  { value: '', label: '全部狀態' },
  { value: 'PENDING', label: '未審核' },
  { value: 'NEEDS_MANUAL_REVIEW', label: '未審核（需特別注意）' },
  { value: 'APPROVED', label: '已核准' },
  { value: 'REPLACED_VOID', label: '已作廢' },
]

const deptOptions = ref([])

onMounted(async () => {
  try {
    const res = await fetchDepartments()
    deptOptions.value = res.data?.data?.departments ?? []
  } catch {
    // fallback：空陣列
  }
})

const categoryOptions = [
  { value: '', label: '全部類別' },
  { value: 'INVOICE', label: '發票' },
  { value: 'RECEIPT', label: '收據' },
  { value: 'LABOR_SERVICE', label: '勞報' },
  { value: 'TRANSPORTATION', label: '交通' },
  { value: 'CREDIT_NOTE', label: '退貨折讓' },
]

// ── v-model computed setters（雙向綁定 store，保證響應式）────────

// 審核狀態：server-side，onChange 觸發 refetch
const statusModel = computed({
  get: () => store.filters.status,
  set: (v) => store.setFilterAndFetch('status', v),
})

// 組別：server-side，onChange 觸發 refetch
const deptModel = computed({
  get: () => store.filters.dept,
  set: (v) => store.setFilterAndFetch('dept', v),
})

// 憑證類別：server-side，onChange 觸發 refetch
const categoryModel = computed({
  get: () => store.filters.category,
  set: (v) => store.setFilterAndFetch('category', v),
})

// ── 日期 / 搜尋：local refs，需明確套用（避免每次 keystroke refetch）

const localDateFrom = ref(store.filters.dateFrom)
const localDateTo = ref(store.filters.dateTo)
const localQ = ref(store.filters.q)

// 當 store 被 resetFilters() 清空時，同步更新 local refs
watch(() => store.filters.dateFrom, (v) => { localDateFrom.value = v })
watch(() => store.filters.dateTo,   (v) => { localDateTo.value = v })
watch(() => store.filters.q,        (v) => { localQ.value = v })

// ── 動作 ────────────────────────────────────────────────────────

function applyDateRange() {
  store.setFilter('dateFrom', localDateFrom.value)
  store.setFilter('dateTo', localDateTo.value)
  store.fetchExpenses()
}

function applySearch() {
  store.setFilterAndFetch('q', localQ.value.trim())
}

function onSearchKeydown(e) {
  if (e.key === 'Enter') applySearch()
}

function clearAll() {
  localDateFrom.value = ''
  localDateTo.value = ''
  localQ.value = ''
  store.resetFilters()
}

// 是否有任何篩選條件（computed，保證響應式更新「清除篩選」按鈕）
const hasActiveFilters = computed(() =>
  !!(store.filters.status || store.filters.dept || store.filters.category ||
     store.filters.dateFrom || store.filters.dateTo || store.filters.q)
)
</script>

<template>
  <div class="bg-white border border-gray-200 rounded-lg p-4 mb-3">
    <div class="flex gap-4">

      <!-- 左側篩選區 -->
      <div class="flex-1 space-y-3">

        <!-- 標題列 -->
        <div class="flex items-center gap-2">
          <SlidersHorizontal :size="14" class="text-gray-500" />
          <span class="text-sm font-medium text-gray-600">篩選條件</span>
          <button
            v-if="hasActiveFilters"
            @click="clearAll"
            class="ml-2 flex items-center gap-1 px-2 py-0.5 rounded text-xs text-red-500 border border-red-200 hover:bg-red-50 transition-colors"
          >
            <X :size="11" />
            清除篩選
          </button>
        </div>

        <!-- Row 1：審核狀態 / 組別 / 憑證類別 -->
        <div class="flex gap-2 flex-wrap">

          <!-- 審核狀態（server-side refetch） -->
          <select
            v-model="statusModel"
            class="border rounded px-2.5 py-1.5 text-sm bg-white cursor-pointer transition-colors"
            :class="store.filters.status ? 'border-blue-400 text-blue-700 font-medium' : 'border-gray-300 text-gray-700'"
          >
            <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>

          <!-- 組別（client-side 即時過濾） -->
          <select
            v-model="deptModel"
            class="border rounded px-2.5 py-1.5 text-sm bg-white cursor-pointer transition-colors"
            :class="store.filters.dept ? 'border-blue-400 text-blue-700 font-medium' : 'border-gray-300 text-gray-700'"
          >
            <option value="">全部組別</option>
            <option v-for="dept in deptOptions" :key="dept" :value="dept">{{ dept }}</option>
          </select>

          <!-- 憑證類別（client-side 即時過濾） -->
          <select
            v-model="categoryModel"
            class="border rounded px-2.5 py-1.5 text-sm bg-white cursor-pointer transition-colors"
            :class="store.filters.category ? 'border-blue-400 text-blue-700 font-medium' : 'border-gray-300 text-gray-700'"
          >
            <option v-for="opt in categoryOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <!-- Row 2：日期範圍 + 搜尋關鍵字 -->
        <div class="flex items-center gap-3 flex-wrap">

          <!-- 上傳日期範圍 -->
          <div class="flex items-center gap-1.5">
            <span class="text-xs text-gray-500 whitespace-nowrap">上傳日期</span>
            <input
              v-model="localDateFrom"
              type="date"
              class="border border-gray-300 rounded px-2 py-1.5 text-sm text-gray-700 w-36"
              :class="localDateFrom ? 'border-blue-400' : ''"
            />
            <span class="text-gray-400 text-sm">~</span>
            <input
              v-model="localDateTo"
              type="date"
              class="border border-gray-300 rounded px-2 py-1.5 text-sm text-gray-700 w-36"
              :class="localDateTo ? 'border-blue-400' : ''"
            />
            <button
              @click="applyDateRange"
              class="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 border border-gray-300 rounded text-sm text-gray-700 transition-colors whitespace-nowrap"
            >
              套用
            </button>
          </div>

          <!-- 分隔線 -->
          <div class="h-5 w-px bg-gray-200 hidden sm:block"></div>

          <!-- 搜尋（案件編號 / 上傳者姓名） -->
          <div class="flex items-center gap-1.5">
            <div class="relative">
              <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
              <input
                v-model="localQ"
                @keydown="onSearchKeydown"
                type="text"
                placeholder="案件編號 / 姓名（Enter 搜尋）"
                class="border rounded pl-7 pr-3 py-1.5 text-sm text-gray-700 w-52 transition-colors"
                :class="store.filters.q ? 'border-blue-400' : 'border-gray-300'"
              />
            </div>
            <button
              @click="applySearch"
              class="px-3 py-1.5 bg-blue-50 hover:bg-blue-100 border border-blue-300 rounded text-sm text-blue-700 transition-colors"
            >
              搜尋
            </button>
          </div>
        </div>

      </div>

      <!-- 右側統計卡片 -->
      <div class="shrink-0 w-56 bg-white border border-gray-200 rounded-lg p-3 text-sm">
        <p class="font-semibold text-gray-700 mb-2">特定時段統計資訊</p>
        <p class="text-gray-500 mb-2 text-xs">
          統計時段：{{ store.stats.dateRange }}
        </p>
        <p v-if="store.stats.hasPendingReview" class="text-red-500 font-semibold mb-2 text-xs">
          尚有未審核單據
        </p>
        <div class="space-y-1 text-gray-600">
          <p class="text-xs">
            總上傳人數：
            <span class="font-semibold text-blue-600">{{ store.stats.totalUploaders }}</span>
          </p>
          <p class="text-xs">
            總費用數量：
            <span class="font-semibold text-blue-600">{{ store.stats.totalExpenses }}</span>
          </p>
          <p class="text-xs">
            總物品圖片數：
            <span class="font-semibold text-blue-600">{{ store.stats.totalImages }}</span>
          </p>
        </div>
      </div>

    </div>
  </div>
</template>
