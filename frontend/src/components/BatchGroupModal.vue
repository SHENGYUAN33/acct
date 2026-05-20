<script setup>
import { ref, onMounted } from 'vue'
import { X, Loader2, ArrowRightLeft } from 'lucide-vue-next'
import { fetchBatchExpenses, moveExpenseImage } from '../api/expenseApi'
import { toast } from 'vue3-toastify'

const props = defineProps({
  expenseId: { type: String, required: true },
})
const emit = defineEmits(['close'])

const BACKEND_BASE = 'http://localhost:8000'

const isLoading = ref(true)
const batchExpenses = ref([])
const movingImageId = ref(null)
const movingImageSourceId = ref(null)
const moveTargetId = ref('')
const isMoving = ref(false)

const STATUS_LABEL = {
  PENDING: '待審核',
  APPROVED: '已核准',
  REJECTED: '已退回',
  NEEDS_MANUAL_REVIEW: '需人工審核',
  SUPPLEMENTED: '已補件',
  REPLACED_VOID: '已作廢',
  WAITING_RETURN: '待退款',
  COMPLETED: '已完成',
}

const STATUS_CLASS = {
  PENDING: 'bg-yellow-100 text-yellow-700',
  APPROVED: 'bg-green-100 text-green-700',
  REJECTED: 'bg-red-100 text-red-700',
  NEEDS_MANUAL_REVIEW: 'bg-orange-100 text-orange-700',
  SUPPLEMENTED: 'bg-blue-100 text-blue-700',
  REPLACED_VOID: 'bg-gray-100 text-gray-500',
  WAITING_RETURN: 'bg-purple-100 text-purple-700',
  COMPLETED: 'bg-teal-100 text-teal-700',
}

const CATEGORY_LABEL = {
  INVOICE: '發票',
  RECEIPT: '收據',
  LABOR_SERVICE: '勞報',
  TRANSPORTATION: '交通',
  CREDIT_NOTE: '退貨折讓',
  INSURANCE: '保險',
  UTILITY: '水電',
  RENTAL: '租金',
  ACCOMMODATION: '住宿',
  POSTAGE: '郵資',
}

function imgUrl(url) {
  if (!url) return ''
  return url.startsWith('http') ? url : `${BACKEND_BASE}/${url}`
}

function categoryLabel(code) {
  return CATEGORY_LABEL[code] ?? code ?? '—'
}

async function loadBatch() {
  isLoading.value = true
  try {
    const res = await fetchBatchExpenses(props.expenseId)
    batchExpenses.value = res.data?.data?.expenses ?? []
  } catch (err) {
    console.error('[BatchGroupModal] 載入批次失敗：', err)
    toast.error('批次資料載入失敗')
    batchExpenses.value = []
  } finally {
    isLoading.value = false
  }
}

onMounted(loadBatch)

function openMove(img, sourceExpenseId) {
  movingImageId.value = img.id
  movingImageSourceId.value = sourceExpenseId
  moveTargetId.value = ''
}

function cancelMove() {
  movingImageId.value = null
  movingImageSourceId.value = null
}

async function confirmMove() {
  if (!moveTargetId.value) return
  isMoving.value = true
  try {
    await moveExpenseImage(movingImageSourceId.value, movingImageId.value, moveTargetId.value)
    toast.success('圖片已搬移')
    movingImageId.value = null
    movingImageSourceId.value = null
    await loadBatch()
  } catch (err) {
    console.error('[BatchGroupModal] 搬移失敗：', err)
    toast.error('搬移失敗，請稍後再試')
  } finally {
    isMoving.value = false
  }
}

function otherExpenses(currentExpenseId) {
  return batchExpenses.value.filter(e => e.id !== currentExpenseId)
}
</script>

<template>
  <!-- Overlay -->
  <div
    class="fixed inset-0 z-[55] bg-black/50 flex items-center justify-center p-4"
    @click.self="emit('close')"
  >
    <!-- Panel -->
    <div class="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">

      <!-- Header -->
      <div class="flex items-center justify-between px-5 py-4 border-b border-gray-200 shrink-0">
        <div>
          <h2 class="text-base font-semibold text-gray-800">批次組</h2>
          <p v-if="!isLoading" class="text-xs text-gray-400 mt-0.5">
            共 {{ batchExpenses.length }} 筆交易
          </p>
        </div>
        <button
          @click="emit('close')"
          class="text-gray-400 hover:text-gray-600 transition-colors"
        >
          <X :size="20" />
        </button>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-y-auto px-5 py-4 space-y-6">

        <!-- Loading -->
        <div v-if="isLoading" class="flex items-center justify-center py-16 text-gray-400">
          <Loader2 :size="28" class="animate-spin mr-2" />
          <span class="text-sm">載入中...</span>
        </div>

        <!-- 無批次資料 -->
        <div
          v-else-if="batchExpenses.length <= 1"
          class="text-center py-12 text-gray-400"
        >
          <ArrowRightLeft :size="40" class="mx-auto mb-3 opacity-30" />
          <p class="text-sm">此筆報帳無批次組資料</p>
          <p class="text-xs mt-1">（無 group_id 或為單筆批次）</p>
        </div>

        <!-- 批次列表 -->
        <template v-else>
          <div
            v-for="expense in batchExpenses"
            :key="expense.id"
            class="border border-gray-200 rounded-lg overflow-hidden"
          >
            <!-- Expense header -->
            <div class="flex items-center gap-3 bg-gray-50 px-4 py-2.5 border-b border-gray-200">
              <span class="font-mono text-sm font-semibold text-gray-800">
                {{ expense.serial_number }}
              </span>
              <span
                :class="STATUS_CLASS[expense.status] ?? 'bg-gray-100 text-gray-500'"
                class="text-xs px-2 py-0.5 rounded font-medium"
              >
                {{ STATUS_LABEL[expense.status] ?? expense.status }}
              </span>
              <span v-if="expense.total_amount != null" class="text-sm text-gray-600 ml-auto">
                NT$ {{ Number(expense.total_amount).toLocaleString() }}
              </span>
            </div>

            <!-- Images grid -->
            <div class="p-3">
              <div v-if="!expense.images || expense.images.length === 0" class="text-xs text-gray-400 py-2 text-center">
                無圖片資料
              </div>
              <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div
                  v-for="img in expense.images"
                  :key="img.id"
                  class="border border-gray-200 rounded-lg overflow-hidden bg-white"
                >
                  <!-- 圖片 -->
                  <img
                    :src="imgUrl(img.image_url)"
                    :alt="img.voucher_category || '圖片'"
                    class="w-full h-28 object-cover"
                  />
                  <!-- 圖片資訊 -->
                  <div class="p-2 space-y-1">
                    <div class="flex flex-wrap gap-1">
                      <span
                        :class="img.is_voucher ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'"
                        class="text-[10px] font-medium px-1.5 py-0.5 rounded"
                      >
                        {{ img.is_voucher ? '憑證' : '非憑證' }}
                      </span>
                      <span
                        v-if="img.voucher_category"
                        class="text-[10px] bg-blue-100 text-blue-700 font-medium px-1.5 py-0.5 rounded"
                      >
                        {{ categoryLabel(img.voucher_category) }}
                      </span>
                    </div>

                    <!-- 移至... 按鈕 -->
                    <template v-if="movingImageId === img.id">
                      <select
                        v-model="moveTargetId"
                        class="w-full text-xs border border-gray-300 rounded px-1.5 py-1 mt-1"
                      >
                        <option value="">— 選擇目標 —</option>
                        <option
                          v-for="target in otherExpenses(expense.id)"
                          :key="target.id"
                          :value="target.id"
                        >
                          {{ target.serial_number }}
                        </option>
                      </select>
                      <div class="flex gap-1 mt-1">
                        <button
                          @click="confirmMove"
                          :disabled="!moveTargetId || isMoving"
                          class="flex-1 text-[10px] bg-indigo-600 text-white rounded py-1 hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {{ isMoving ? '搬移中...' : '確認' }}
                        </button>
                        <button
                          @click="cancelMove"
                          class="flex-1 text-[10px] border border-gray-300 text-gray-600 rounded py-1 hover:bg-gray-50"
                        >
                          取消
                        </button>
                      </div>
                    </template>
                    <button
                      v-else
                      @click="openMove(img, expense.id)"
                      class="w-full text-[10px] text-indigo-600 hover:text-indigo-800 underline mt-0.5 text-left"
                    >
                      移至...
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>

      </div>
    </div>
  </div>
</template>
