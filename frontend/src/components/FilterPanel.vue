<script setup>
import { ref } from 'vue'
import { SlidersHorizontal } from 'lucide-vue-next'
import { useExpenseStore } from '../stores/expenseStore'

const store = useExpenseStore()

// 部門選項
const deptOptions = ['', '製片組', '美術組', '攝影組', '燈光組', '其他']
const categoryOptions = ['', '餐費', '交通費', '器材費', '場地費', '道具費', '其他費用']

// 本地篩選暫存
const localCheckStatus = ref('')
const localDept = ref('')
const localCategory = ref('')
const localSubItem = ref('')
const localDateFrom = ref('2025/12/20')
const localDateTo = ref('2026/02/24')
const localSubmitter = ref('')

function applyFilters() {
  store.setFilter('checkStatus', localCheckStatus.value)
  store.setFilter('dept', localDept.value)
  store.setFilter('category', localCategory.value)
  store.setFilter('dateFrom', localDateFrom.value)
  store.setFilter('dateTo', localDateTo.value)
  store.setFilter('submitter', localSubmitter.value)
}
</script>

<template>
  <div class="bg-white border border-gray-200 rounded-lg p-4 mb-3">
    <div class="flex gap-4">

      <!-- 左側篩選區 -->
      <div class="flex-1 space-y-3">

        <!-- Row 0：篩選條件按鈕（從 Header 移入） -->
        <div>
          <button class="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 transition-colors">
            <SlidersHorizontal :size="14" />
            篩選條件
          </button>
        </div>

        <!-- Row 1：下拉選單組 -->
        <div class="flex gap-2 flex-wrap">
          <select
            v-model="localCheckStatus"
            @change="applyFilters"
            class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 bg-white min-w-[100px] cursor-pointer"
          >
            <option value="">勾選</option>
            <option value="checked">已勾選</option>
            <option value="unchecked">未勾選</option>
          </select>

          <select
            v-model="localDept"
            @change="applyFilters"
            class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 bg-white min-w-[100px] cursor-pointer"
          >
            <option value="">組別</option>
            <option v-for="dept in deptOptions.filter(d => d)" :key="dept" :value="dept">
              {{ dept }}
            </option>
          </select>

          <select
            v-model="localCategory"
            @change="applyFilters"
            class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 bg-white min-w-[100px] cursor-pointer"
          >
            <option value="">類別</option>
            <option v-for="cat in categoryOptions.filter(c => c)" :key="cat" :value="cat">
              {{ cat }}
            </option>
          </select>

          <select
            v-model="localSubItem"
            @change="applyFilters"
            class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 bg-white min-w-[100px] cursor-pointer"
          >
            <option value="">細項</option>
            <option value="meal">餐點</option>
            <option value="transport">交通</option>
            <option value="equipment">設備</option>
          </select>
        </div>

        <!-- Row 2：專案期間 -->
        <div class="flex items-center gap-2 flex-wrap">
          <select class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 bg-white min-w-[100px] cursor-pointer">
            <option>專案期間</option>
          </select>
          <input
            v-model="localDateFrom"
            @change="applyFilters"
            type="text"
            placeholder="2025/12/20"
            class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 w-32"
          />
          <span class="text-gray-400 text-sm">~</span>
          <input
            v-model="localDateTo"
            @change="applyFilters"
            type="text"
            placeholder="2026/02/24"
            class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 w-32"
          />
        </div>

        <!-- Row 3：費用提報者搜尋 -->
        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-600 whitespace-nowrap">費用提報者</label>
          <input
            v-model="localSubmitter"
            @input="applyFilters"
            type="text"
            placeholder="搜尋"
            class="border border-gray-300 rounded px-2.5 py-1.5 text-sm text-gray-700 w-40"
          />
        </div>
      </div>

      <!-- 右側統計卡片 -->
      <div class="shrink-0 w-56 bg-white border border-gray-200 rounded-lg p-3 text-sm">
        <p class="font-semibold text-gray-700 mb-2">特定時段統計資訊</p>
        <p class="text-gray-500 mb-2">
          統計時段：{{ store.stats.dateRange }}
        </p>
        <p v-if="store.stats.hasPendingReview" class="text-red-500 font-semibold mb-2">
          尚有未審核單據
        </p>
        <div class="space-y-1 text-gray-600">
          <p>
            總上傳人數：
            <span class="font-semibold text-blue-600">{{ store.stats.totalUploaders }}</span>
          </p>
          <p>
            總費用數量：
            <span class="font-semibold text-blue-600">{{ store.stats.totalExpenses }}</span>
          </p>
          <p>
            總物品圖片數：
            <span class="font-semibold text-blue-600">{{ store.stats.totalImages }}</span>
          </p>
        </div>
      </div>

    </div>
  </div>
</template>
