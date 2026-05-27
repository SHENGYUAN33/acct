<script setup>
import { ref, computed, watch } from 'vue'
import { useExpenseStore } from '../stores/expenseStore'
import { getExpense, fetchExpenses, fetchRelatedExpenses, resolveDuplicate } from '../api/expenseApi'
import { toast } from 'vue3-toastify'
import { Pencil, Trash2, Plus, ChevronsUpDown, ChevronRight, Link2, GripVertical } from 'lucide-vue-next'
import ConfirmModal from './ConfirmModal.vue'
import BatchGroupModal from './BatchGroupModal.vue'

const store = useExpenseStore()

const BACKEND_BASE = 'http://localhost:8000'

const CATEGORY_LABEL = {
  INVOICE: '發票', RECEIPT: '收據', LABOR_SERVICE: '勞報',
  TRANSPORTATION: '交通', CREDIT_NOTE: '退貨折讓',
}

function normalizeImageUrls(exp) {
  if (!exp) return exp
  const raw = exp.voucher_categories
  const parsed = raw
    ? (typeof raw === 'string' ? JSON.parse(raw) : raw)
    : null
  return {
    ...exp,
    image_url: (exp.image_url || []).map(u => u.startsWith('http') ? u : `${BACKEND_BASE}/${u}`),
    item_image_url: (exp.item_image_url || []).map(u => u.startsWith('http') ? u : `${BACKEND_BASE}/${u}`),
    voucher_categories: parsed ? parsed.map(c => CATEGORY_LABEL[c] ?? c) : null,
  }
}

// 展開的列 ID 集合（元件本地狀態，與篩選無關）
const expandedRows = ref(new Set())
// 已載入的原單資料快取（key: 新單 expense.id, value: 原單 expense data）
const parentCache = ref({})
// 載入中的 expense id 集合
const fetchingParent = ref(new Set())
// WAITING_RETURN 補件快取（key: invoice expense.id, value: 補件 expense | null | 'loading' | 'error'）
const supplementCache = ref({})

// store 刷新後清除 supplementCache，確保展開時拿到最新補件狀態
watch(() => store.expenses, () => { supplementCache.value = {} })

// 批次組 Modal
const batchModalExpenseId = ref(null)
function openBatchModal(expense) { batchModalExpenseId.value = expense.id }
function closeBatchModal() { batchModalExpenseId.value = null }

async function toggleExpand(expense) {
  const id = expense.id
  const next = new Set(expandedRows.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
    // 抓取關聯補件（使用 parent_id 查詢，可靠不依賴 invoice_number）
    if (!(id in supplementCache.value)) {
      supplementCache.value = { ...supplementCache.value, [id]: 'loading' }
      try {
        const res = await fetchRelatedExpenses(id)
        const items = res.data?.data ?? []
        const sup = items.find(e =>
          ['RETURN_SUPPLEMENT', 'VOID_REPLACE', 'CREDIT_NOTE'].includes(e.relation_type)
        ) ?? null
        supplementCache.value = { ...supplementCache.value, [id]: normalizeImageUrls(sup) }
      } catch {
        supplementCache.value = { ...supplementCache.value, [id]: 'error' }
      }
    }
    // VOID_REPLACE：尚未快取則自動抓取原單
    if ((expense.relation_type === 'VOID_REPLACE' || expense.relation_type === 'CREDIT_NOTE') && expense.parent_id && !parentCache.value[id]) {
      const fetching = new Set(fetchingParent.value)
      fetching.add(id)
      fetchingParent.value = fetching
      try {
        const res = await getExpense(expense.parent_id)
        parentCache.value = { ...parentCache.value, [id]: res.data.data }
      } catch {
        // 靜默失敗，不影響展開
      } finally {
        const f = new Set(fetchingParent.value)
        f.delete(id)
        fetchingParent.value = f
      }
    }
  }
  expandedRows.value = next
}

// 狀態設定
const statusConfig = {
  PENDING: { dot: 'bg-red-500', label: '未審核', textColor: 'text-red-500' },
  APPROVED: { dot: 'bg-green-500', label: '已核准', textColor: 'text-green-600' },
  REJECTED: { dot: 'bg-gray-400', label: '已退回', textColor: 'text-gray-500' },
  NEEDS_MANUAL_REVIEW: { dot: 'bg-orange-400', label: '未審核\n(需特別注意!)', textColor: 'text-orange-500' },
  SUPPLEMENTED: { dot: 'bg-yellow-400', label: '已補件', textColor: 'text-yellow-600' },
  WAITING_RETURN: { dot: 'bg-orange-500', label: '待退貨', textColor: 'text-orange-600' },
  COMPLETED: { dot: 'bg-teal-500', label: '已結清', textColor: 'text-teal-600' },
  REPLACED_VOID: { dot: 'bg-gray-300', label: '已作廢', textColor: 'text-gray-400' },
}

function getStatusConfig(status) {
  return statusConfig[status] || statusConfig.PENDING
}

// 確認刪除 Modal 狀態
const isConfirmOpen = ref(false)
const pendingDeleteExpense = ref(null)

// 刪除費用：開啟確認 Modal
function handleDelete(expense) {
  pendingDeleteExpense.value = expense
  isConfirmOpen.value = true
}

// 使用者確認刪除後執行
async function confirmDelete() {
  isConfirmOpen.value = false
  const expense = pendingDeleteExpense.value
  pendingDeleteExpense.value = null
  try {
    await store.deleteExpense(expense.id)
    toast.success('已成功刪除該筆報帳！')
  } catch {
    toast.error('刪除失敗，請稍後再試')
  }
}

// 重複憑證處理
async function handleDuplicateDismiss(expense) {
  try {
    await resolveDuplicate(expense.id, 'dismiss')
    toast.success('已確認為合法單據，警示已清除')
    store.fetchExpenses()
  } catch {
    toast.error('操作失敗，請稍後再試')
  }
}

async function handleDuplicateDelete(expense) {
  try {
    await resolveDuplicate(expense.id, 'delete')
    toast.success('重複費用單已刪除')
    store.fetchExpenses()
  } catch {
    toast.error('刪除失敗，請稍後再試')
  }
}

// 金額格式化
function formatAmount(amount) {
  if (amount === null || amount === undefined) return '-'
  return `$${Number(amount).toLocaleString()}`
}

// 已配對的補件（parent_id 已設定）不在主表格顯示（改由父憑證展開子列呈現）
const visibleExpenses = computed(() =>
  store.paginatedExpenses.filter(e =>
    !(e.relation_type === 'RETURN_SUPPLEMENT' && e.referenced_invoice_number) &&
    !e.parent_id
  )
)

// ── 拖曳排序 ─────────────────────────────────────────────────────
const draggedId = ref(null)   // 正在被拖曳的列 ID
const dragOverId = ref(null)  // 目前懸停的目標列 ID

function onDragStart(e, expense) {
  draggedId.value = expense.id
  e.dataTransfer.effectAllowed = 'move'
}

function onDragOver(e, expense) {
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
  dragOverId.value = expense.id
}

async function onDrop(e, expense) {
  e.preventDefault()
  if (draggedId.value && draggedId.value !== expense.id) {
    try {
      await store.reorderExpenses(draggedId.value, expense.id)
    } catch {
      toast.error('排序儲存失敗，請稍後再試')
    }
  }
  draggedId.value = null
  dragOverId.value = null
}

function onDragEnd() {
  draggedId.value = null
  dragOverId.value = null
}
</script>

<template>
  <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
    <div class="overflow-x-auto">
      <table class="w-full text-sm border-collapse">
        <!-- 表頭 -->
        <thead>
          <tr class="bg-gray-100 border-b border-gray-200">
            <!-- 拖曳 handle 佔位 -->
            <th class="w-5 px-1"></th>
            <!-- 展開箭頭佔位 -->
            <th class="w-6 px-1"></th>
            <!-- Checkbox -->
            <th class="w-8 px-2 py-2.5">
              <input
                type="checkbox"
                :checked="store.allChecked"
                @change="store.toggleAll"
                class="cursor-pointer"
              />
            </th>
            <!-- # -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">
              <div class="flex items-center gap-1">
                # <ChevronsUpDown :size="12" class="text-gray-400" />
              </div>
            </th>
            <!-- 狀態 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">
              <div class="flex items-center gap-1">
                狀態 <ChevronsUpDown :size="12" class="text-gray-400" />
              </div>
            </th>
            <!-- 上傳人 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">
              <div class="flex items-center gap-1">
                上傳人 <ChevronsUpDown :size="12" class="text-gray-400" />
              </div>
            </th>
            <!-- 上傳者組別 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">上傳者組別</th>
            <!-- 費用提報者 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">費用提報者</th>
            <!-- 操作 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">
              <div class="flex items-center gap-1">
                操作 <ChevronsUpDown :size="12" class="text-gray-400" />
              </div>
            </th>
            <!-- 審核狀態 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">審核狀態</th>
            <!-- 細項 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">
              <div class="flex items-center gap-1">
                細項 <ChevronsUpDown :size="12" class="text-gray-400" />
              </div>
            </th>
            <!-- 憑證類別 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">憑證類別</th>
            <!-- 費用影像 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">費用影像</th>
            <!-- 物品影像 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">物品影像</th>
            <!-- 項目說明 -->
            <th class="px-3 py-2.5 text-left text-gray-600 font-medium whitespace-nowrap">
              <div class="flex items-center gap-1">
                項目說明 <ChevronsUpDown :size="12" class="text-gray-400" />
              </div>
            </th>
          </tr>
        </thead>

        <!-- 表格主體 -->
        <tbody>
          <template v-for="expense in visibleExpenses" :key="expense.id">
            <!-- 主列 -->
            <tr
              class="border-b border-gray-100 transition-colors"
              :class="[
                expense.status === 'REPLACED_VOID'
                  ? 'opacity-40 bg-gray-100'
                  : dragOverId === expense.id && draggedId !== expense.id
                    ? 'bg-blue-50 border-t-2 border-blue-400'
                    : draggedId === expense.id
                      ? 'opacity-50 bg-yellow-50'
                      : 'hover:bg-gray-50',
                expandedRows.has(expense.id) && expense.status !== 'REPLACED_VOID' ? 'bg-gray-50' : ''
              ]"
              draggable="true"
              @dragstart="onDragStart($event, expense)"
              @dragover="onDragOver($event, expense)"
              @drop="onDrop($event, expense)"
              @dragend="onDragEnd"
            >
              <!-- 拖曳 handle -->
              <td class="w-5 px-1 py-2 text-center">
                <GripVertical
                  :size="14"
                  class="text-gray-300 hover:text-gray-500 cursor-grab active:cursor-grabbing mx-auto"
                />
              </td>

              <!-- 展開箭頭 -->
              <td class="w-6 px-1 py-2 text-center">
                <button
                  @click="toggleExpand(expense)"
                  class="text-gray-400 hover:text-gray-600 transition-transform duration-150"
                  :class="{ 'rotate-90': expandedRows.has(expense.id) }"
                  :title="expense.relation_type === 'VOID_REPLACE' ? '展開查看被取代的原單' : '展開細節'"
                >
                  <Link2 v-if="expense.relation_type === 'VOID_REPLACE' || expense.relation_type === 'CREDIT_NOTE'" :size="14" class="text-red-400" />
                  <ChevronRight v-else :size="14" />
                </button>
              </td>

              <!-- Checkbox -->
              <td class="w-8 px-2 py-2 text-center">
                <input
                  type="checkbox"
                  :checked="store.checkedIds.has(expense.id)"
                  @change="store.toggleCheck(expense.id)"
                  class="cursor-pointer"
                />
              </td>

              <!-- 案件編號 -->
              <td class="px-3 py-2 text-gray-700 font-medium whitespace-nowrap font-mono text-xs">
                <div class="flex items-center gap-1 flex-wrap">
                  <span>{{ expense.serial_number || '#' + expense.serial }}</span>
                  <!-- Sprint 3：觸發來源 Badge -->
                  <span
                    v-if="expense.trigger_by === 'auto_split'"
                    class="text-[10px] px-1 py-0.5 rounded bg-yellow-100 text-yellow-700"
                    title="自動送出"
                  >⏱</span>
                  <!-- 重複憑證警示 -->
                  <span
                    v-if="expense.possible_duplicate_of"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-600 border border-red-200 font-sans"
                    title="此憑證疑似已上傳過，請由管理員裁決"
                  >⚠ 疑似重複</span>
                </div>
              </td>

              <!-- 狀態燈號 -->
              <td class="px-3 py-2">
                <span
                  class="inline-block w-3 h-3 rounded-full"
                  :class="getStatusConfig(expense.status).dot"
                  :title="getStatusConfig(expense.status).label"
                ></span>
              </td>

              <!-- 上傳人 -->
              <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ expense.uploader_name }}</td>

              <!-- 上傳者組別 -->
              <td class="px-3 py-2 text-gray-600 whitespace-nowrap">{{ expense.uploader_dept }}</td>

              <!-- 費用提報者 -->
              <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ expense.submitter_name }}</td>

              <!-- 操作按鈕 -->
              <td class="px-3 py-2 whitespace-nowrap">
                <div class="flex items-center gap-1.5">
                  <button
                    @click="store.openAudit(expense)"
                    class="w-7 h-7 bg-blue-500 hover:bg-blue-600 text-white rounded flex items-center justify-center transition-colors"
                    title="編輯 / 審核"
                  >
                    <Pencil :size="13" />
                  </button>
                  <button
                    @click="handleDelete(expense)"
                    class="w-7 h-7 bg-red-500 hover:bg-red-600 text-white rounded flex items-center justify-center transition-colors"
                    title="刪除"
                  >
                    <Trash2 :size="13" />
                  </button>
                  <button
                    @click="openBatchModal(expense)"
                    class="w-7 h-7 bg-green-500 hover:bg-green-600 text-white rounded flex items-center justify-center transition-colors"
                    title="批次組"
                  >
                    <Plus :size="13" />
                  </button>
                  <!-- 重複憑證裁決按鈕 -->
                  <template v-if="expense.possible_duplicate_of">
                    <button
                      @click="handleDuplicateDismiss(expense)"
                      class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 hover:bg-gray-200 text-gray-600 border border-gray-300 transition-colors"
                      title="確認合法，清除重複警示"
                    >合法</button>
                    <button
                      @click="handleDuplicateDelete(expense)"
                      class="text-[10px] px-1.5 py-0.5 rounded bg-red-50 hover:bg-red-100 text-red-600 border border-red-300 transition-colors"
                      title="刪除此筆重複費用單"
                    >刪除</button>
                  </template>
                </div>
              </td>

              <!-- 審核狀態文字 -->
              <td class="px-3 py-2 whitespace-nowrap">
                <div class="flex items-center gap-1 flex-wrap">
                  <span
                    class="text-sm font-medium whitespace-pre-line"
                    :class="getStatusConfig(expense.status).textColor"
                  >
                    {{ getStatusConfig(expense.status).label }}
                  </span>
                  <span
                    v-if="expense.relation_type === 'VOID_REPLACE'"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-600 border border-red-200"
                    :title="`換單（原單：${expense.referenced_invoice_number || '?'}）`"
                  >換單</span>
                  <span
                    v-else-if="expense.relation_type === 'CREDIT_NOTE'"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-600 border border-purple-200"
                    :title="`折讓單（原單：${expense.referenced_invoice_number || '?'}）`"
                  >折讓</span>
                  <span
                    v-else-if="expense.relation_type === 'SUPPLEMENT'"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-600 border border-blue-200"
                    title="差額補足"
                  >補足</span>
                  <span
                    v-if="!expense.is_active"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-500 border border-gray-300"
                    :title="expense.void_reason || '已作廢'"
                  >作廢</span>
                </div>
              </td>

              <!-- 細項（空白，後端尚未提供） -->
              <td class="px-3 py-2 text-gray-400">-</td>

              <!-- 憑證類別 -->
              <td class="px-3 py-2 whitespace-nowrap">
                <template v-if="expense.voucher_categories && expense.voucher_categories.length">
                  <span
                    v-for="cat in expense.voucher_categories"
                    :key="cat"
                    class="inline-block text-xs px-1.5 py-0.5 rounded mr-1 mb-0.5 bg-blue-100 text-blue-700"
                  >
                    {{ cat }}
                  </span>
                </template>
                <span v-else class="text-gray-400">-</span>
              </td>

              <!-- 費用影像縮圖（顯示第一張） -->
              <td class="px-3 py-2">
                <div
                  v-if="expense.image_url && expense.image_url.length > 0"
                  class="w-10 h-10 rounded overflow-hidden border border-gray-200"
                >
                  <img :src="expense.image_url[0]" alt="費用影像" class="w-full h-full object-cover" />
                </div>
                <div
                  v-else
                  class="w-10 h-10 bg-gray-200 rounded border border-gray-300 flex items-center justify-center"
                >
                  <span class="text-gray-400 text-xs">無</span>
                </div>
              </td>

              <!-- 物品影像縮圖（顯示第一張） -->
              <td class="px-3 py-2">
                <div
                  v-if="expense.item_image_url && expense.item_image_url.length > 0"
                  class="w-10 h-10 rounded overflow-hidden border border-gray-200"
                >
                  <img :src="expense.item_image_url[0]" alt="物品影像" class="w-full h-full object-cover" />
                </div>
                <div
                  v-else
                  class="w-10 h-10 bg-gray-200 rounded border border-gray-300 flex items-center justify-center"
                >
                  <span class="text-gray-400 text-xs">無</span>
                </div>
              </td>

              <!-- 項目說明 -->
              <td class="px-3 py-2 text-gray-600 max-w-xs">
                <div class="line-clamp-2 text-xs leading-relaxed">
                  {{ expense.item_description || '-' }}
                </div>
                <div v-if="expense.total_amount" class="text-xs text-gray-400 mt-0.5">
                  {{ formatAmount(expense.total_amount) }}
                </div>
              </td>
            </tr>

            <!-- 展開列（細節區塊） -->
            <tr v-if="expandedRows.has(expense.id)" class="bg-blue-50">
              <td colspan="14" class="px-6 py-3">
                <div class="grid grid-cols-4 gap-4 text-xs text-gray-600">
                  <div>
                    <span class="font-medium text-gray-500">案件編號：</span>
                    <span class="font-mono">{{ expense.serial_number || '-' }}</span>
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">上傳日期：</span>
                    {{ expense.upload_date || '-' }}
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">消費日期：</span>
                    {{ expense.expense_date || '-' }}
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">發票號碼：</span>
                    {{ expense.invoice_number || '-' }}
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">總金額：</span>
                    {{ formatAmount(expense.total_amount) }}
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">未稅金額：</span>
                    {{ formatAmount(expense.net_amount) }}
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">稅額：</span>
                    {{ formatAmount(expense.tax_amount) }}
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">賣方統編：</span>
                    {{ expense.seller_tax_id || '-' }}
                  </div>
                  <div>
                    <span class="font-medium text-gray-500">賣方名稱：</span>
                    {{ expense.seller_name || '-' }}
                  </div>
                  <div v-if="expense.reject_reason" class="col-span-4">
                    <span class="font-medium text-red-500">退件原因：</span>
                    <span class="text-red-600">{{ expense.reject_reason }}</span>
                  </div>
                </div>
              </td>
            </tr>

            <!-- 原單子列（VOID_REPLACE 展開時顯示被取代的舊單） -->
            <tr
              v-if="expandedRows.has(expense.id) && (expense.relation_type === 'VOID_REPLACE' || expense.relation_type === 'CREDIT_NOTE')"
              class="border-b border-dashed border-gray-300"
            >
              <td colspan="14" class="bg-gray-100 px-6 py-2.5">
                <!-- 載入中 -->
                <div v-if="fetchingParent.has(expense.id)" class="text-xs text-gray-400 flex items-center gap-1.5">
                  <svg class="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10" class="opacity-25"/>
                    <path d="M4 12a8 8 0 018-8" class="opacity-75"/>
                  </svg>
                  載入原單資料中…
                </div>
                <!-- 原單資料 -->
                <div v-else-if="parentCache[expense.id]" class="flex items-start gap-6 text-xs">
                  <div class="flex items-center gap-1.5 font-medium shrink-0 pt-0.5"
                    :class="expense.relation_type === 'CREDIT_NOTE' ? 'text-purple-400' : 'text-gray-400'">
                    <Link2 :size="12" />
                    {{ expense.relation_type === 'CREDIT_NOTE' ? '原始報帳' : '原單' }}
                  </div>
                  <div class="grid grid-cols-5 gap-x-6 gap-y-1 text-gray-600 flex-1">
                    <div>
                      <span class="text-gray-400">案件編號：</span>
                      <span class="font-mono font-medium text-gray-700">{{ parentCache[expense.id].serial_number }}</span>
                    </div>
                    <div>
                      <span class="text-gray-400">狀態：</span>
                      <span class="text-gray-500">已作廢</span>
                      <span v-if="parentCache[expense.id].void_reason" class="ml-1 text-gray-400">（{{ parentCache[expense.id].void_reason }}）</span>
                    </div>
                    <div>
                      <span class="text-gray-400">發票號碼：</span>
                      <span class="font-mono">{{ parentCache[expense.id].invoice_number || '-' }}</span>
                    </div>
                    <div>
                      <span class="text-gray-400">金額：</span>
                      <span>{{ parentCache[expense.id].total_amount ? 'NT$ ' + Number(parentCache[expense.id].total_amount).toLocaleString() : '-' }}</span>
                    </div>
                    <div>
                      <span class="text-gray-400">消費日期：</span>
                      <span>{{ parentCache[expense.id].expense_date || '-' }}</span>
                    </div>
                  </div>
                </div>
                <!-- 找不到原單（防禦） -->
                <div v-else class="text-xs text-gray-400">
                  無法載入原單資料（ID: {{ expense.parent_id }}）
                </div>
              </td>
            </tr>

            <!-- 待退貨補件子列：載入中 -->
            <tr
              v-if="expandedRows.has(expense.id) && supplementCache[expense.id] === 'loading'"
              class="border-b border-dashed border-purple-200"
            >
              <td colspan="15" class="bg-purple-50 px-6 py-2.5">
                <div class="flex items-center gap-1.5 text-xs text-gray-400">
                  <svg class="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10" class="opacity-25"/>
                    <path d="M4 12a8 8 0 018-8" class="opacity-75"/>
                  </svg>
                  載入補件資料中…
                </div>
              </td>
            </tr>

            <!-- 待退貨補件子列：錯誤 -->
            <tr
              v-if="expandedRows.has(expense.id) && supplementCache[expense.id] === 'error'"
              class="border-b border-dashed border-purple-200"
            >
              <td colspan="15" class="bg-purple-50 px-6 py-2.5 text-xs text-red-400">無法載入補件資料</td>
            </tr>

            <!-- 待退貨補件子列：尚無補件（僅 WAITING_RETURN 顯示此提示） -->
            <tr
              v-if="expandedRows.has(expense.id) && expense.status === 'WAITING_RETURN' && supplementCache[expense.id] === null"
              class="border-b border-dashed border-purple-200"
            >
              <td colspan="15" class="bg-purple-50 px-6 py-2.5">
                <div class="text-xs text-purple-400 opacity-60 flex items-center gap-1">
                  <Link2 :size="11" />
                  待退貨補件：尚未收到對應物品照
                </div>
              </td>
            </tr>

            <!-- 待退貨補件子列：完整列（有補件時顯示，含配對完成後 PENDING 狀態） -->
            <tr
              v-if="expandedRows.has(expense.id) && supplementCache[expense.id] && supplementCache[expense.id] !== 'loading' && supplementCache[expense.id] !== 'error'"
              class="border-b border-dashed border-purple-200 bg-purple-50"
            >
              <!-- td1: 拖曳佔位 -->
              <td class="w-5 px-1 py-1.5"></td>

              <!-- td2: 關係圖示 -->
              <td class="w-6 px-1 py-1.5 text-center">
                <Link2 :size="12" class="text-purple-300 mx-auto" />
              </td>

              <!-- td3: Checkbox（空） -->
              <td class="w-8 px-2 py-1.5"></td>

              <!-- td4: 案件編號 -->
              <td class="px-3 py-1.5 text-gray-700 font-medium whitespace-nowrap font-mono text-xs">
                {{ supplementCache[expense.id].serial_number }}
              </td>

              <!-- td5: 狀態燈號 -->
              <td class="px-3 py-1.5">
                <span
                  class="inline-block w-3 h-3 rounded-full"
                  :class="getStatusConfig(supplementCache[expense.id].status).dot"
                  :title="getStatusConfig(supplementCache[expense.id].status).label"
                ></span>
              </td>

              <!-- td6: 上傳人 -->
              <td class="px-3 py-1.5 text-gray-700 whitespace-nowrap text-xs">
                {{ supplementCache[expense.id].uploader_name }}
              </td>

              <!-- td7: 上傳者組別 -->
              <td class="px-3 py-1.5 text-gray-600 whitespace-nowrap text-xs">
                {{ supplementCache[expense.id].uploader_dept || '-' }}
              </td>

              <!-- td8: 費用提報者 -->
              <td class="px-3 py-1.5 text-gray-700 whitespace-nowrap text-xs">
                {{ supplementCache[expense.id].submitter_name || '-' }}
              </td>

              <!-- td9: 操作 -->
              <td class="px-3 py-1.5 whitespace-nowrap">
                <div class="flex items-center gap-1.5">
                  <button
                    @click="store.openAudit(supplementCache[expense.id])"
                    class="w-7 h-7 bg-blue-500 hover:bg-blue-600 text-white rounded flex items-center justify-center transition-colors"
                    title="編輯 / 審核"
                  >
                    <Pencil :size="13" />
                  </button>
                  <button
                    @click="handleDelete(supplementCache[expense.id])"
                    class="w-7 h-7 bg-red-500 hover:bg-red-600 text-white rounded flex items-center justify-center transition-colors"
                    title="刪除"
                  >
                    <Trash2 :size="13" />
                  </button>
                  <button
                    @click="openBatchModal(supplementCache[expense.id])"
                    class="w-7 h-7 bg-green-500 hover:bg-green-600 text-white rounded flex items-center justify-center transition-colors"
                    title="批次組詳情"
                  >
                    <Plus :size="13" />
                  </button>
                </div>
              </td>

              <!-- td10: 審核狀態 + 情境類型 badge -->
              <td class="px-3 py-1.5 whitespace-nowrap">
                <div class="flex items-center gap-1 flex-wrap">
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-600 border border-purple-200">補件</span>
                  <span
                    v-if="supplementCache[expense.id]?.relation_type === 'VOID_REPLACE'"
                    class="text-[9px] px-1 py-0.5 rounded bg-blue-100 text-blue-600"
                  >換新發票</span>
                  <span
                    v-else-if="supplementCache[expense.id]?.relation_type === 'CREDIT_NOTE'"
                    class="text-[9px] px-1 py-0.5 rounded bg-orange-100 text-orange-600"
                  >折讓單</span>
                  <span
                    v-else-if="supplementCache[expense.id]?.relation_type === 'RETURN_SUPPLEMENT'"
                    class="text-[9px] px-1 py-0.5 rounded bg-purple-100 text-purple-600"
                  >換貨收據</span>
                </div>
              </td>

              <!-- td11: 細項 -->
              <td class="px-3 py-1.5 text-gray-400 text-xs">-</td>

              <!-- td12: 憑證類別 -->
              <td class="px-3 py-1.5 whitespace-nowrap">
                <template v-if="supplementCache[expense.id].voucher_categories?.length">
                  <span
                    v-for="cat in supplementCache[expense.id].voucher_categories"
                    :key="cat"
                    class="inline-block text-xs px-1.5 py-0.5 rounded mr-1 mb-0.5 bg-blue-100 text-blue-700"
                  >{{ cat }}</span>
                </template>
                <span v-else class="text-gray-400 text-xs">-</span>
              </td>

              <!-- td13: 費用影像 -->
              <td class="px-3 py-1.5">
                <div
                  v-if="supplementCache[expense.id].image_url?.length"
                  class="w-10 h-10 rounded overflow-hidden border border-purple-200"
                >
                  <img :src="supplementCache[expense.id].image_url[0]" alt="費用影像" class="w-full h-full object-cover" />
                </div>
                <div v-else class="w-10 h-10 bg-gray-200 rounded border border-gray-300 flex items-center justify-center">
                  <span class="text-gray-400 text-xs">無</span>
                </div>
              </td>

              <!-- td14: 物品影像 -->
              <td class="px-3 py-1.5">
                <div
                  v-if="supplementCache[expense.id].item_image_url?.length"
                  class="w-10 h-10 rounded overflow-hidden border border-purple-200"
                >
                  <img :src="supplementCache[expense.id].item_image_url[0]" alt="物品影像" class="w-full h-full object-cover" />
                </div>
                <div v-else class="w-10 h-10 bg-gray-200 rounded border border-gray-300 flex items-center justify-center">
                  <span class="text-gray-400 text-xs">無</span>
                </div>
              </td>

              <!-- td15: 項目說明 + 金額 -->
              <td class="px-3 py-1.5 text-gray-600 max-w-xs">
                <div class="line-clamp-2 text-xs leading-relaxed">
                  {{ supplementCache[expense.id].item_description || '-' }}
                </div>
                <div v-if="supplementCache[expense.id].total_amount" class="text-xs text-gray-400 mt-0.5">
                  {{ formatAmount(supplementCache[expense.id].total_amount) }}
                </div>
              </td>
            </tr>
          </template>

          <!-- 空資料提示 -->
          <tr v-if="visibleExpenses.length === 0">
            <td colspan="14" class="px-4 py-10 text-center text-gray-400">
              目前無符合條件的報帳紀錄
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 刪除確認 Modal -->
  <ConfirmModal
    :open="isConfirmOpen"
    :description="`確定要刪除此筆費用（${pendingDeleteExpense ? (pendingDeleteExpense.serial_number || '#' + pendingDeleteExpense.serial) : ''}）嗎？此操作無法復原。`"
    @confirm="confirmDelete"
    @cancel="isConfirmOpen = false"
  />

  <!-- 批次組 Modal -->
  <BatchGroupModal
    v-if="batchModalExpenseId"
    :expense-id="batchModalExpenseId"
    @close="closeBatchModal"
  />
</template>
