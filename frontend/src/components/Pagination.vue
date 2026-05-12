<script setup>
import { computed } from 'vue'
import { useExpenseStore } from '../stores/expenseStore'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-vue-next'

const store = useExpenseStore()

// 顯示的頁碼範圍（最多顯示 7 個頁碼按鈕）
const visiblePages = computed(() => {
  const total = store.totalPages
  const current = store.currentPage
  const delta = 2
  const pages = []

  const rangeStart = Math.max(1, current - delta)
  const rangeEnd = Math.min(total, current + delta)

  if (rangeStart > 1) {
    pages.push(1)
    if (rangeStart > 2) pages.push('...')
  }

  for (let i = rangeStart; i <= rangeEnd; i++) {
    pages.push(i)
  }

  if (rangeEnd < total) {
    if (rangeEnd < total - 1) pages.push('...')
    pages.push(total)
  }

  return pages
})

const pageSizeOptions = [20, 50, 100]
</script>

<template>
  <div class="flex items-center justify-between px-3 py-2.5 border-t border-gray-200 bg-white text-sm">
    <!-- 左側：每頁筆數 -->
    <div class="flex items-center gap-2 text-gray-500">
      <select
        :value="store.pageSize"
        @change="store.setPageSize(Number($event.target.value))"
        class="border border-gray-300 rounded px-2 py-1 text-sm bg-white cursor-pointer"
      >
        <option v-for="size in pageSizeOptions" :key="size" :value="size">
          {{ size }}
        </option>
      </select>
      <span>entries per page</span>
      <span class="text-gray-400 ml-2">
        共 {{ store.totalCount }} 筆
      </span>
    </div>

    <!-- 右側：頁碼導覽 -->
    <div class="flex items-center gap-1">
      <!-- 第一頁 -->
      <button
        @click="store.setPage(1)"
        :disabled="store.currentPage === 1"
        class="w-7 h-7 flex items-center justify-center rounded border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        <ChevronsLeft :size="14" />
      </button>

      <!-- 上一頁 -->
      <button
        @click="store.setPage(store.currentPage - 1)"
        :disabled="store.currentPage === 1"
        class="w-7 h-7 flex items-center justify-center rounded border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        <ChevronLeft :size="14" />
      </button>

      <!-- 頁碼按鈕 -->
      <template v-for="page in visiblePages" :key="page">
        <span v-if="page === '...'" class="w-7 h-7 flex items-center justify-center text-gray-400">
          ···
        </span>
        <button
          v-else
          @click="store.setPage(page)"
          class="w-7 h-7 flex items-center justify-center rounded border text-sm transition-colors"
          :class="
            store.currentPage === page
              ? 'bg-blue-500 border-blue-500 text-white font-medium'
              : 'border-gray-300 text-gray-600 hover:bg-gray-100'
          "
        >
          {{ page }}
        </button>
      </template>

      <!-- 下一頁 -->
      <button
        @click="store.setPage(store.currentPage + 1)"
        :disabled="store.currentPage === store.totalPages"
        class="w-7 h-7 flex items-center justify-center rounded border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        <ChevronRight :size="14" />
      </button>

      <!-- 最後頁 -->
      <button
        @click="store.setPage(store.totalPages)"
        :disabled="store.currentPage === store.totalPages"
        class="w-7 h-7 flex items-center justify-center rounded border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        <ChevronsRight :size="14" />
      </button>
    </div>
  </div>
</template>
