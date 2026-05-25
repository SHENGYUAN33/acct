<script setup>
import { ref, onMounted } from 'vue'
import { X, Loader2, GripVertical, ArrowRightLeft } from 'lucide-vue-next'
import { fetchBatchExpenses, moveExpenseImage } from '../api/expenseApi'
import { toast } from 'vue3-toastify'

const props = defineProps({
  expenseId: { type: String, required: true },
})
const emit = defineEmits(['close'])

const BACKEND_BASE = 'http://localhost:8000'

const isLoading = ref(true)
const batchExpenses = ref([])
const dragging = ref(null)         // { imgId, sourceExpenseId }
const dragOverExpenseId = ref(null)
const isMoving = ref(false)
const pendingMove = ref(null)      // { imgId, sourceExpenseId, targetExpenseId, targetSerial }

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

const STATUS_DOT = {
  PENDING: 'bg-yellow-400',
  APPROVED: 'bg-green-500',
  REJECTED: 'bg-red-500',
  NEEDS_MANUAL_REVIEW: 'bg-orange-400',
  SUPPLEMENTED: 'bg-blue-400',
  REPLACED_VOID: 'bg-gray-400',
  WAITING_RETURN: 'bg-purple-400',
  COMPLETED: 'bg-teal-500',
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

function shortGroupId(id) {
  return id ? id.slice(0, 8) + '...' : '—'
}

function categoryLabel(code) {
  return CATEGORY_LABEL[code] ?? code ?? '—'
}

async function loadBatch() {
  isLoading.value = true
  try {
    const res = await fetchBatchExpenses(props.expenseId)
    const expenses = res.data?.data?.expenses ?? []
    // 「目前」那筆（觸發 Modal 的 expense）固定排第一欄
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

// ── Drag-and-drop handlers ──────────────────────────────────────

function onDragStart(event, img, sourceExpenseId) {
  dragging.value = { imgId: img.id, sourceExpenseId }
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', img.id)
  // 讓拖曳中的卡片變半透明（CSS class 由 :class 綁定）
}

function onDragOver(event, targetExpenseId) {
  if (!dragging.value || dragging.value.sourceExpenseId === targetExpenseId) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  dragOverExpenseId.value = targetExpenseId
}

function onDragLeave(event) {
  // 只在真正離開欄位（而非進入子元素）時清除高亮
  if (!event.currentTarget.contains(event.relatedTarget)) {
    dragOverExpenseId.value = null
  }
}

function onDragEnd() {
  dragging.value = null
  dragOverExpenseId.value = null
}

function onDrop(event, targetExpenseId) {
  event.preventDefault()
  if (!dragging.value || dragging.value.sourceExpenseId === targetExpenseId) {
    dragging.value = null
    dragOverExpenseId.value = null
    return
  }
  const { imgId, sourceExpenseId } = dragging.value
  const targetExpense = batchExpenses.value.find(e => e.id === targetExpenseId)
  dragging.value = null
  dragOverExpenseId.value = null
  // 暫存待確認動作，顯示確認對話框
  pendingMove.value = {
    imgId,
    sourceExpenseId,
    targetExpenseId,
    targetSerial: targetExpense?.serial_number ?? targetExpenseId,
  }
}

async function executePendingMove() {
  if (!pendingMove.value) return
  const { imgId, sourceExpenseId, targetExpenseId } = pendingMove.value
  pendingMove.value = null
  isMoving.value = true
  try {
    await moveExpenseImage(sourceExpenseId, imgId, targetExpenseId)
    toast.success('圖片已移動')
    await loadBatch()
  } catch (err) {
    console.error('[BatchGroupModal] 搬移失敗：', err)
    toast.error('移動失敗，請稍後再試')
  } finally {
    isMoving.value = false
  }
}

function cancelPendingMove() {
  pendingMove.value = null
}

function isDraggingFromThisColumn(expenseId) {
  return dragging.value?.sourceExpenseId === expenseId
}
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
            <h2 class="text-lg font-semibold text-gray-900 tracking-tight">批次組</h2>
            <div v-if="!isLoading" class="flex items-center gap-3 mt-0.5">
              <span class="text-xs text-gray-400">
                共 {{ batchExpenses.length }} 筆交易
              </span>
              <span
                v-if="batchExpenses[0]?.group_id"
                class="text-xs font-mono text-gray-300"
              >
                group: {{ shortGroupId(batchExpenses[0].group_id) }}
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

        <!-- Drag hint -->
        <div v-if="!isLoading && batchExpenses.length > 1" class="mt-3 flex items-center gap-1.5 text-xs text-indigo-500 bg-indigo-50 px-3 py-1.5 rounded-lg w-fit">
          <GripVertical :size="13" />
          拖拉圖片卡片可將其移至其他交易欄位
        </div>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-hidden relative">

        <!-- Loading -->
        <div v-if="isLoading" class="flex items-center justify-center h-full text-gray-400">
          <Loader2 :size="28" class="animate-spin mr-2" />
          <span class="text-sm">載入中...</span>
        </div>

        <!-- 無批次資料 -->
        <div
          v-else-if="batchExpenses.length === 0"
          class="flex flex-col items-center justify-center h-full text-gray-400 gap-3"
        >
          <ArrowRightLeft :size="40" class="opacity-25" />
          <div class="text-center">
            <p class="text-sm font-medium">此筆報帳無批次組資料</p>
            <p class="text-xs mt-1 text-gray-300">無 group_id 或為單筆批次</p>
          </div>
        </div>

        <!-- Kanban 欄 -->
        <div
          v-else
          class="flex gap-4 overflow-x-auto h-full p-5 items-start"
        >
          <div
            v-for="expense in batchExpenses"
            :key="expense.id"
            class="min-w-[230px] w-[230px] shrink-0 flex flex-col rounded-xl border border-gray-200 overflow-hidden bg-gray-50"
          >
            <!-- 欄 Header -->
            <div class="px-3 py-2.5 bg-white border-b border-gray-100">
              <div class="flex items-center gap-1.5 mb-1">
                <span
                  class="w-2 h-2 rounded-full shrink-0"
                  :class="STATUS_DOT[expense.status] ?? 'bg-gray-300'"
                ></span>
                <span class="font-mono text-xs font-semibold text-gray-800 truncate">
                  {{ expense.serial_number }}
                </span>
                <!-- 目前查看的那筆標記 -->
                <span
                  v-if="expense.id === expenseId"
                  class="ml-auto text-[10px] bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded shrink-0"
                >
                  目前
                </span>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-[11px] text-gray-400">
                  {{ STATUS_LABEL[expense.status] ?? expense.status }}
                </span>
                <span
                  v-if="expense.total_amount != null"
                  class="text-[11px] font-medium text-gray-600"
                >
                  NT${{ Number(expense.total_amount).toLocaleString() }}
                </span>
              </div>
            </div>

            <!-- Drop Zone -->
            <div
              class="flex-1 min-h-[160px] p-2 space-y-2 transition-all duration-150"
              :class="{
                'bg-indigo-50 ring-2 ring-indigo-300 ring-inset': dragOverExpenseId === expense.id,
                'opacity-60': isMoving,
              }"
              @dragover="onDragOver($event, expense.id)"
              @dragleave="onDragLeave"
              @drop="onDrop($event, expense.id)"
            >
              <!-- 圖片卡片 -->
              <template v-if="expense.images && expense.images.length > 0">
                <div
                  v-for="img in expense.images"
                  :key="img.id"
                  draggable="true"
                  class="flex items-center gap-2 bg-white border border-gray-200 rounded-lg p-1.5 select-none transition-opacity"
                  :class="{
                    'cursor-grab active:cursor-grabbing': !isMoving,
                    'opacity-40': dragging?.imgId === img.id,
                    'cursor-not-allowed': isMoving,
                  }"
                  @dragstart="onDragStart($event, img, expense.id)"
                  @dragend="onDragEnd"
                >
                  <!-- Drag handle -->
                  <GripVertical :size="14" class="text-gray-300 shrink-0" />

                  <!-- 縮圖 -->
                  <img
                    :src="imgUrl(img.image_url)"
                    :alt="img.voucher_category || '圖片'"
                    class="w-10 h-10 object-cover rounded border border-gray-100 shrink-0 pointer-events-none"
                    draggable="false"
                  />

                  <!-- 資訊 -->
                  <div class="flex-1 min-w-0 space-y-0.5">
                    <div class="flex flex-wrap gap-1">
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
                        {{ categoryLabel(img.voucher_category) }}
                      </span>
                    </div>
                    <div
                      v-if="img.expense_category"
                      class="text-[10px] text-gray-400 truncate"
                    >
                      {{ img.expense_category }}
                    </div>
                  </div>
                </div>
              </template>

              <!-- 空欄提示 -->
              <div
                v-else
                class="h-full min-h-[100px] flex items-center justify-center border-2 border-dashed rounded-lg transition-colors"
                :class="dragOverExpenseId === expense.id
                  ? 'border-indigo-300 text-indigo-400'
                  : 'border-gray-200 text-gray-300'"
              >
                <span class="text-xs">拖放至此</span>
              </div>

              <!-- 拖拉進入提示（有圖片但 drag over 時的輔助提示）-->
              <div
                v-if="dragOverExpenseId === expense.id && expense.images && expense.images.length > 0"
                class="flex items-center justify-center border-2 border-dashed border-indigo-300 rounded-lg py-2 text-xs text-indigo-400"
              >
                放開以移動至此
              </div>
            </div>
          </div>
        </div>

        <!-- 移動中 overlay -->
        <div
          v-if="isMoving"
          class="absolute inset-0 flex items-center justify-center bg-white/60 backdrop-blur-sm"
        >
          <div class="flex items-center gap-2 text-gray-500 text-sm bg-white border border-gray-200 shadow-lg rounded-xl px-4 py-3">
            <Loader2 :size="18" class="animate-spin text-indigo-500" />
            移動中...
          </div>
        </div>
      </div>

    </div>

    <!-- 移動確認對話框（z-[60] 蓋在 Modal 之上）-->
    <div
      v-if="pendingMove"
      class="fixed inset-0 z-[60] bg-black/40 flex items-center justify-center p-4"
      @click.self="cancelPendingMove"
    >
      <div class="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <div class="flex items-center gap-2 text-gray-800 font-semibold text-base">
          <ArrowRightLeft :size="18" class="text-indigo-500 shrink-0" />
          確認移動照片？
        </div>
        <p class="text-sm text-gray-600 leading-relaxed">
          此操作將把照片移至
          <span class="font-medium text-gray-900">{{ pendingMove.targetSerial }}</span>
          欄位，移動後可再次拖拉調整位置。
        </p>
        <div class="flex justify-end gap-2 pt-1">
          <button
            @click="cancelPendingMove"
            class="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
          >
            取消
          </button>
          <button
            @click="executePendingMove"
            :disabled="isMoving"
            class="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {{ isMoving ? '移動中...' : '確定移動' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
