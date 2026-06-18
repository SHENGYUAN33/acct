<script setup>
import { ref, computed, onMounted } from 'vue'
import { X, Loader2, ImageOff } from 'lucide-vue-next'
import { fetchBatchExpenses } from '../api/expenseApi'
import { toast } from 'vue3-toastify'
import { secureImgUrl as imgUrl, isViewableImage } from '../utils/imageUrl'
import { getStatusConfig } from '../constants/status.js'
import { getVoucherLabel } from '../constants/voucher.js'

const props = defineProps({
  expenseId: { type: String, required: true },
})
const emit = defineEmits(['close'])

const isLoading = ref(true)
const batchExpenses = ref([])

const lightboxOpen = ref(false)
const lightboxSrc = ref('')

function openLightbox(src) {
  lightboxSrc.value = src
  lightboxOpen.value = true
}

const expense = computed(() => batchExpenses.value[0] ?? null)



async function loadBatch() {
  isLoading.value = true
  try {
    const res = await fetchBatchExpenses(props.expenseId)
    const expenses = res.data?.data?.expenses ?? []
    expenses.sort((a, b) => {
      if (a.id === props.expenseId) return -1
      if (b.id === props.expenseId) return 1
      return 0
    })
    batchExpenses.value = expenses
  } catch (err) {
    console.error('[BatchGroupModal] 載入批次失敗：', err)
    toast.error('批次資料載入失敗')
    batchExpenses.value = []
  } finally {
    isLoading.value = false
  }
}

onMounted(loadBatch)
</script>

<template>
  <!-- Overlay -->
  <div
    class="fixed inset-0 z-[55] bg-black/60 flex items-center justify-center p-4"
    @click.self="emit('close')"
  >
    <!-- Panel -->
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-5xl h-[85vh] flex flex-col overflow-hidden">

      <!-- Header -->
      <div class="shrink-0 px-6 pt-5 pb-4 border-b border-gray-100">
        <div class="flex items-start justify-between">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 tracking-tight">上傳內容</h2>
            <div v-if="!isLoading && expense" class="flex items-center gap-2 mt-1">
              <span
                class="w-2 h-2 rounded-full shrink-0"
                :class="getStatusConfig(expense.status).dot"
              ></span>
              <span class="text-xs font-mono font-semibold text-gray-700">{{ expense.serial_number }}</span>
              <span class="text-xs text-gray-400">{{ getStatusConfig(expense.status).label }}</span>
              <span v-if="expense.total_amount != null" class="text-xs font-medium text-gray-600">
                NT${{ Number(expense.total_amount).toLocaleString() }}
              </span>
            </div>
          </div>
          <button
            @click="emit('close')"
            class="text-gray-300 hover:text-gray-600 transition-colors mt-0.5"
          >
            <X :size="20" />
          </button>
        </div>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-y-auto">

        <!-- Loading -->
        <div v-if="isLoading" class="flex items-center justify-center py-16 text-gray-400">
          <Loader2 :size="28" class="animate-spin mr-2" />
          <span class="text-sm">載入中...</span>
        </div>

        <!-- 無資料 -->
        <div
          v-else-if="!expense"
          class="flex flex-col items-center justify-center py-16 text-gray-400 gap-3"
        >
          <ImageOff :size="40" class="opacity-25" />
          <p class="text-sm">此筆報帳無上傳資料</p>
        </div>

        <!-- 圖片區 -->
        <div v-else class="p-5">
          <!-- 有圖片 -->
          <div
            v-if="expense.images && expense.images.length > 0"
            class="flex flex-wrap gap-4"
          >
            <div
              v-for="img in expense.images"
              :key="img.id"
              class="flex flex-col items-center gap-2 w-40"
            >
              <!-- 縮圖 -->
              <div class="w-40 h-40 rounded-xl border border-gray-200 overflow-hidden bg-gray-50 shrink-0 flex items-center justify-center">
                <img
                  v-if="isViewableImage(img.image_url)"
                  :src="imgUrl(img.image_url)"
                  :alt="img.voucher_category || '圖片'"
                  class="w-full h-full object-cover cursor-zoom-in hover:opacity-90 transition-opacity"
                  draggable="false"
                  @click="openLightbox(imgUrl(img.image_url))"
                />
                <a
                  v-else
                  :href="imgUrl(img.image_url)"
                  target="_blank"
                  class="flex flex-col items-center gap-1 text-gray-500 hover:text-blue-600"
                >
                  <span class="text-3xl">📄</span>
                  <span class="text-xs">開啟 PDF</span>
                </a>
              </div>

              <!-- 標籤 -->
              <div class="flex flex-wrap justify-center gap-1">
                <span
                  :class="img.is_voucher
                    ? 'bg-green-100 text-green-700'
                    : 'bg-gray-100 text-gray-400'"
                  class="text-[10px] font-medium px-1.5 py-0.5 rounded leading-tight"
                >
                  {{ img.is_voucher ? '憑證' : '非憑證' }}
                </span>
                <span
                  v-if="img.voucher_category"
                  class="text-[10px] bg-blue-50 text-blue-600 font-medium px-1.5 py-0.5 rounded leading-tight"
                >
                  {{ getVoucherLabel(img.voucher_category) }}
                </span>
              </div>

              <!-- 費用科目 -->
              <div v-if="img.expense_category" class="text-[10px] text-gray-400 text-center leading-tight">
                {{ img.expense_category }}
              </div>
            </div>
          </div>

          <!-- 無圖片 -->
          <div
            v-else
            class="flex flex-col items-center justify-center py-10 text-gray-300 gap-2 border-2 border-dashed border-gray-200 rounded-xl"
          >
            <ImageOff :size="32" class="opacity-50" />
            <span class="text-sm">此筆報帳尚無圖片</span>
          </div>

          <!-- 備註 -->
          <div class="mt-5 pt-4 border-t border-gray-100">
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1.5">備註</p>
            <p v-if="expense.user_description" class="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{{ expense.user_description }}</p>
            <p v-else class="text-sm text-gray-300">無備註</p>
          </div>
        </div>

      </div>

    </div>
  </div>

  <!-- Lightbox -->
  <div
    v-if="lightboxOpen"
    class="fixed inset-0 z-[70] bg-black/90 flex items-center justify-center p-4 cursor-zoom-out"
    @click="lightboxOpen = false"
  >
    <img
      :src="lightboxSrc"
      alt="圖片預覽"
      class="max-w-full max-h-full rounded-lg shadow-2xl object-contain"
      @click.stop
    />
  </div>
</template>
