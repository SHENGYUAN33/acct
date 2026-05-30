<script setup>
import { ref, computed, onMounted } from 'vue'
import { X, Loader2, PackageX, CheckCircle2, ChevronRight, ChevronDown, Search, Link2, Unlink2, Trash2 } from 'lucide-vue-next'
import { fetchWaitingReturns, fetchExpenses, fetchRelatedExpenses, updateExpense, deleteExpense, pairExpense } from '../api/expenseApi'
import { toast } from 'vue3-toastify'
import { API_BASE_URL } from '../utils/axios'

const emit = defineEmits(['close', 'count-changed'])

const BACKEND_BASE = API_BASE_URL

// ── 資料 ───────────────────────────────────────────────────────────
const isLoading = ref(true)
const cases = ref([])
const orphanSupplements = ref([])

// ── 左欄展開 ───────────────────────────────────────────────────────
const expandedInvoiceId = ref(null)

// ── 右欄搜尋 ───────────────────────────────────────────────────────
const searchQuery = ref('')
const isSearching = ref(false)
const searchResults = ref([])

// ── 拖拉配對 ───────────────────────────────────────────────────────
const draggingSupplementId = ref(null)
const dragOverInvoiceId = ref(null)
const pendingLink = ref(null)  // { supplementId, supplementSerial, invoiceId, invoiceSerial, invoiceNumber }
const isLinking = ref(false)

// ── 動作按鈕 ───────────────────────────────────────────────────────
const unlinkingId = ref(null)
const finalizingInvoiceId = ref(null)

// ── 左欄：手動加入原始交易 ─────────────────────────────────────────
const leftSearchQuery = ref('')
const isLeftSearching = ref(false)
const leftSearchResults = ref([])
const showLeftSearch = ref(false)

// ── 燈箱 ───────────────────────────────────────────────────────────
const lightboxUrl = ref(null)
function openLightbox(url) { lightboxUrl.value = url }
function closeLightbox() { lightboxUrl.value = null }

const STATUS_LABEL = {
  PENDING: '待審核', APPROVED: '已核准', REJECTED: '已退回',
  NEEDS_MANUAL_REVIEW: '需人工審核', SUPPLEMENTED: '已補件',
  REPLACED_VOID: '已作廢', WAITING_RETURN: '待退貨', COMPLETED: '已結清',
}
const STATUS_DOT = {
  PENDING: 'bg-yellow-400', APPROVED: 'bg-green-500', REJECTED: 'bg-red-500',
  NEEDS_MANUAL_REVIEW: 'bg-orange-400', SUPPLEMENTED: 'bg-blue-400',
  REPLACED_VOID: 'bg-gray-400', WAITING_RETURN: 'bg-purple-500', COMPLETED: 'bg-teal-500',
}

function imgUrl(url) {
  if (!url) return ''
  return url.startsWith('http') ? url : `${BACKEND_BASE}/${url}`
}

// ── 右欄顯示（搜尋中顯示搜尋結果，否則顯示孤立補件）────────────────
const rightPanelItems = computed(() => {
  if (searchQuery.value.trim() && searchResults.value.length > 0) return searchResults.value
  return orphanSupplements.value
})

// ── 載入 ───────────────────────────────────────────────────────────
async function loadData() {
  isLoading.value = true
  try {
    const res = await fetchWaitingReturns()
    cases.value = res.data?.data?.cases ?? []
    orphanSupplements.value = res.data?.data?.orphan_supplements ?? []
    emit('count-changed')
  } catch {
    toast.error('待退貨資料載入失敗')
    cases.value = []
    orphanSupplements.value = []
  } finally {
    isLoading.value = false
  }
}
onMounted(loadData)

// ── 左欄：手風琴展開 ───────────────────────────────────────────────
function toggleExpand(invoiceId) {
  expandedInvoiceId.value = expandedInvoiceId.value === invoiceId ? null : invoiceId
}

// ── 右欄：名稱搜尋 ─────────────────────────────────────────────────
async function searchSupplements() {
  const q = searchQuery.value.trim()
  if (!q) { searchResults.value = []; return }
  isSearching.value = true
  try {
    // Bug 7：提高 page_size 上限，確保搜尋結果涵蓋所有補件類型
    const res = await fetchExpenses({ q, page_size: 100 })
    searchResults.value = (res.data?.data?.items ?? [])
      .filter(e => ['RETURN_SUPPLEMENT', 'VOID_REPLACE', 'CREDIT_NOTE'].includes(e.relation_type))
  } catch {
    toast.error('搜尋失敗')
    searchResults.value = []
  } finally {
    isSearching.value = false
  }
}

function clearSearch() {
  searchQuery.value = ''
  searchResults.value = []
}

// ── 拖拉：開始（從右欄補件卡片）────────────────────────────────────
function onDragStart(event, supplement) {
  draggingSupplementId.value = supplement.id
  event.dataTransfer.effectAllowed = 'link'
  event.dataTransfer.setData('text/plain', supplement.id)
}

function onDragEnd() {
  draggingSupplementId.value = null
  dragOverInvoiceId.value = null
}

// ── 拖拉：Drop 至左欄憑證行 ────────────────────────────────────────
function onDragOver(event, invoiceId) {
  if (!draggingSupplementId.value) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'link'
  dragOverInvoiceId.value = invoiceId
}

function onDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) {
    dragOverInvoiceId.value = null
  }
}

function onDrop(event, invoice) {
  event.preventDefault()
  if (!draggingSupplementId.value) { dragOverInvoiceId.value = null; return }

  // 找被拖拉的補件
  const all = [...rightPanelItems.value, ...orphanSupplements.value]
  const supplement = all.find(s => s.id === draggingSupplementId.value)

  pendingLink.value = {
    supplementId: draggingSupplementId.value,
    supplementSerial: supplement?.serial_number ?? '（未知）',
    invoiceId: invoice.id,
    invoiceSerial: invoice.serial_number,
    invoiceNumber: invoice.invoice_number,
  }
  draggingSupplementId.value = null
  dragOverInvoiceId.value = null
}

// ── 確認配對（pair endpoint 設定 parent_id 與 referenced_invoice_number）──
async function confirmLink() {
  const { supplementId, invoiceId } = pendingLink.value
  pendingLink.value = null
  isLinking.value = true
  try {
    await pairExpense(supplementId, invoiceId)
    toast.success('配對成功')
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('配對失敗，請稍後再試')
  } finally {
    isLinking.value = false
  }
}

// ── 一鍵確認建議配對 ────────────────────────────────────────────────
async function confirmSuggestedMatch(sup) {
  if (!sup.suggested_match) return
  isLinking.value = true
  try {
    await pairExpense(sup.id, sup.suggested_match.expense_id)
    toast.success('建議配對已確認')
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('配對失敗，請稍後再試')
  } finally {
    isLinking.value = false
  }
}

// ── 情境類型標籤 ────────────────────────────────────────────────────
function relationTypeLabel(type) {
  if (type === 'VOID_REPLACE') return '換新發票'
  if (type === 'CREDIT_NOTE') return '折讓單'
  if (type === 'RETURN_SUPPLEMENT') return '換貨收據'
  return ''
}

// ── 左欄：搜尋原始交易 ─────────────────────────────────────────────
async function searchLeftPanel() {
  const q = leftSearchQuery.value.trim()
  if (!q) { leftSearchResults.value = []; return }
  isLeftSearching.value = true
  try {
    const res = await fetchExpenses({ q, page_size: 20 })
    const existingIds = new Set(cases.value.map(c => c.invoice.id))
    leftSearchResults.value = (res.data?.data?.items ?? []).filter(e => !existingIds.has(e.id))
  } catch {
    toast.error('搜尋失敗')
    leftSearchResults.value = []
  } finally {
    isLeftSearching.value = false
  }
}

async function addToLeftPanel(expense) {
  // 1. 將憑證狀態設為 WAITING_RETURN，確保 loadData() 重建後仍顯示於左側
  if (expense.status !== 'WAITING_RETURN') {
    try {
      await updateExpense(expense.id, { status: 'WAITING_RETURN' })
      expense = { ...expense, status: 'WAITING_RETURN' }
    } catch {
      toast.error('無法將該憑證標記為待退貨，請稍後再試')
      return
    }
  }
  // 2. 查詢已存在的補件（parent_id 指向此憑證）
  let existingSupplements = []
  try {
    const res = await fetchRelatedExpenses(expense.id)
    existingSupplements = (res.data?.data ?? [])
      .filter(e => ['RETURN_SUPPLEMENT', 'VOID_REPLACE', 'CREDIT_NOTE'].includes(e.relation_type))
  } catch { /* 靜默失敗，顯示空補件 */ }
  cases.value = [{ invoice: expense, supplements: existingSupplements }, ...cases.value]
  leftSearchQuery.value = ''
  leftSearchResults.value = []
  showLeftSearch.value = false
  emit('count-changed')
}

// ── 案件層級確認完成：所有補件 → COMPLETED，憑證 → PENDING ──────────
// 確保無論補件個別狀態為何，都能一鍵將案件移出待退貨管理
async function finalizeCase(item) {
  const invoice = item.invoice
  if (finalizingInvoiceId.value === invoice.id) return
  finalizingInvoiceId.value = invoice.id
  try {
    const ops = []
    for (const sup of (item.supplements ?? [])) {
      if (!sup.parent_id) ops.push(pairExpense(sup.id, invoice.id))
      if (sup.status !== 'PENDING') ops.push(updateExpense(sup.id, { status: 'PENDING' }))
    }
    ops.push(updateExpense(invoice.id, { status: 'PENDING' }))
    await Promise.all(ops)
    toast.success('案件已完成，憑證移至待審核')
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('操作失敗，請稍後再試')
  } finally {
    finalizingInvoiceId.value = null
  }
}

// ── 刪除孤立補件 ───────────────────────────────────────────────────
const deletingOrphanId = ref(null)
async function deleteOrphanSupplement(sup) {
  if (deletingOrphanId.value === sup.id) return
  if (!confirm(`確定刪除孤立補件 ${sup.serial_number}？此操作無法復原。`)) return
  deletingOrphanId.value = sup.id
  try {
    await deleteExpense(sup.id)
    toast.success(`孤立補件 ${sup.serial_number} 已刪除`)
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('刪除失敗，請稍後再試')
  } finally {
    deletingOrphanId.value = null
  }
}

// ── 解除配對 ───────────────────────────────────────────────────────
async function unlinkSupplement(supplement, invoice) {
  if (unlinkingId.value === supplement.id) return
  unlinkingId.value = supplement.id
  try {
    const ops = [
      updateExpense(supplement.id, {
        parent_id: null,
        referenced_invoice_number: null,
      }),
    ]
    // finalizeCase 後父憑證狀態為 PENDING，解除時還原為 WAITING_RETURN
    if (invoice && invoice.status === 'PENDING') {
      ops.push(updateExpense(invoice.id, { status: 'WAITING_RETURN' }))
    }
    await Promise.all(ops)
    toast.success(`補件 ${supplement.serial_number} 已解除配對`)
    await loadData()
    // 手動加入的原始憑證（非 WAITING_RETURN）不在後端查詢範圍內，loadData 後補回左側
    if (invoice && !cases.value.some(c => c.invoice.id === invoice.id)) {
      cases.value = [{ invoice, supplements: [] }, ...cases.value]
    }
    emit('count-changed')
  } catch {
    toast.error('解除配對失敗')
  } finally {
    unlinkingId.value = null
  }
}
</script>

<template>
  <div class="fixed inset-0 z-[55] bg-black/60 flex items-center justify-center p-4" @click.self="emit('close')">
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-5xl h-[88vh] flex flex-col overflow-hidden">

      <!-- Header -->
      <div class="shrink-0 px-5 pt-4 pb-3 border-b border-gray-100 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <PackageX :size="17" class="text-purple-500" />
          <span class="font-semibold text-gray-900 tracking-tight">待退貨管理</span>
          <span v-if="!isLoading" class="text-xs text-gray-400 ml-1">{{ cases.length }} 筆待退貨案件</span>
        </div>
        <button @click="emit('close')" class="text-gray-300 hover:text-gray-600 transition-colors">
          <X :size="20" />
        </button>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="flex-1 flex items-center justify-center text-gray-400">
        <Loader2 :size="28" class="animate-spin mr-2" />
        <span class="text-sm">載入中...</span>
      </div>

      <!-- Main: 左右分欄 -->
      <div v-else class="flex-1 flex min-h-0">

        <!-- ── 左欄：待退貨憑證清單 ── -->
        <div class="w-[58%] border-r border-gray-100 flex flex-col min-h-0">

          <!-- 手動加入原始交易 -->
          <div class="shrink-0 px-3 pt-2 pb-1.5 border-b border-gray-100">
            <button
              @click="showLeftSearch = !showLeftSearch"
              class="text-[11px] text-purple-500 hover:text-purple-700 flex items-center gap-1"
            >
              <span>{{ showLeftSearch ? '▲' : '▼' }}</span>
              手動加入原始交易至左側
            </button>
            <div v-if="showLeftSearch" class="mt-1.5 space-y-1">
              <div class="flex gap-1">
                <input
                  v-model="leftSearchQuery"
                  @keyup.enter="searchLeftPanel"
                  placeholder="EXP編號 / 發票號碼 / 上傳者..."
                  class="flex-1 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400"
                />
                <button
                  @click="searchLeftPanel"
                  :disabled="isLeftSearching"
                  class="flex items-center gap-1 px-2.5 py-1.5 bg-purple-500 hover:bg-purple-600 text-white text-xs rounded-lg disabled:opacity-50 transition-colors"
                >
                  <Loader2 v-if="isLeftSearching" :size="11" class="animate-spin" />
                  <Search v-else :size="11" />
                </button>
              </div>
              <div v-if="leftSearchResults.length" class="bg-white border border-gray-200 rounded-lg overflow-hidden max-h-40 overflow-y-auto">
                <div
                  v-for="exp in leftSearchResults"
                  :key="exp.id"
                  @click="addToLeftPanel(exp)"
                  class="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-purple-50 border-b border-gray-100 last:border-0"
                >
                  <span class="font-mono text-[11px] text-gray-800">{{ exp.serial_number }}</span>
                  <span v-if="exp.invoice_number" class="text-[10px] font-mono text-gray-400">{{ exp.invoice_number }}</span>
                  <span class="text-[10px] text-gray-500 truncate">{{ exp.uploader_name }}</span>
                  <span class="ml-auto text-[10px] bg-purple-100 text-purple-600 px-1.5 py-0.5 rounded">加入</span>
                </div>
              </div>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto">

            <!-- 左欄無案件空狀態 -->
            <div v-if="cases.length === 0"
              class="flex flex-col items-center justify-center h-full text-gray-300 text-xs gap-2 pb-8">
              <PackageX :size="32" class="opacity-30" />
              <span class="text-gray-400 text-sm font-medium">目前無待退貨案件</span>
              <span class="text-gray-300">備註含「待退貨」的報帳會顯示於此</span>
            </div>

          <div class="divide-y divide-gray-100">
            <div
              v-for="(item, idx) in cases"
              :key="item.invoice.id"
              class="transition-colors"
              :class="dragOverInvoiceId === item.invoice.id ? 'bg-purple-50' : ''"
              @dragover="onDragOver($event, item.invoice.id)"
              @dragleave="onDragLeave"
              @drop="onDrop($event, item.invoice)"
            >
              <!-- 憑證列標題 -->
              <div
                class="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-gray-50 select-none"
                @click="toggleExpand(item.invoice.id)"
              >
                <!-- 展開箭頭 -->
                <component
                  :is="expandedInvoiceId === item.invoice.id ? ChevronDown : ChevronRight"
                  :size="15"
                  class="text-gray-400 shrink-0"
                />

                <!-- 狀態點 -->
                <span class="w-2 h-2 rounded-full shrink-0"
                  :class="STATUS_DOT[item.invoice.status] ?? 'bg-gray-300'" />

                <!-- 案件編號 -->
                <span class="font-mono text-xs font-semibold text-gray-800">{{ item.invoice.serial_number }}</span>

                <!-- 金額 -->
                <span v-if="item.invoice.total_amount != null" class="text-xs text-gray-500">
                  NT${{ Number(item.invoice.total_amount).toLocaleString() }}
                </span>

                <!-- 發票號 -->
                <span v-if="item.invoice.invoice_number" class="text-[11px] font-mono text-gray-400 truncate">
                  {{ item.invoice.invoice_number }}
                </span>

                <!-- 右側 badge -->
                <div class="ml-auto flex items-center gap-1.5 shrink-0">
                  <!-- 補件狀態 badge -->
                  <span v-if="item.supplements?.length > 0"
                    class="text-[10px] bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded">
                    已配對{{ item.supplements.length > 1 ? ` (${item.supplements.length})` : '' }}
                  </span>
                  <span v-else
                    class="text-[10px] bg-orange-100 text-orange-500 px-1.5 py-0.5 rounded">待配對</span>

                  <!-- Drop 指示（拖拉中） -->
                  <span v-if="dragOverInvoiceId === item.invoice.id"
                    class="text-[10px] bg-purple-100 text-purple-600 px-2 py-0.5 rounded animate-pulse">
                    放開以配對
                  </span>
                </div>
              </div>

              <!-- 展開區：補件圖片 + 按鈕 -->
              <div v-if="expandedInvoiceId === item.invoice.id" class="px-4 pb-4 space-y-3">

                <!-- 原始憑證照片 -->
                <div>
                  <p class="text-[10px] text-gray-400 mb-1.5 font-medium">原始憑證照片</p>
                  <div class="flex flex-wrap gap-2">
                    <img
                      v-for="(url, i) in (item.invoice.image_url ?? [])"
                      :key="'inv-img-'+i"
                      :src="imgUrl(url)"
                      alt="憑證照片"
                      @click="openLightbox(imgUrl(url))"
                      class="w-14 h-14 object-cover rounded-lg border border-gray-200 cursor-zoom-in hover:opacity-80 transition-opacity"
                    />
                    <span v-if="!(item.invoice.image_url?.length)" class="text-xs text-gray-300 italic py-2">（無原始照片）</span>
                  </div>
                </div>

                <!-- 已配對的補件（多筆 v-for） -->
                <div
                  v-for="sup in (item.supplements ?? [])"
                  :key="sup.id"
                  class="bg-gray-50 rounded-xl border border-gray-200 p-3 space-y-2"
                >
                  <div class="flex items-center gap-1.5">
                    <span class="w-1.5 h-1.5 rounded-full shrink-0"
                      :class="STATUS_DOT[sup.status] ?? 'bg-gray-300'" />
                    <span class="font-mono text-[11px] text-gray-600">{{ sup.serial_number }}</span>
                    <span class="text-[10px] text-gray-400">{{ sup.uploader_name }}</span>
                  </div>

                  <!-- 補件圖片（image_url = 費用憑證照，item_image_url = 退貨物品照） -->
                  <div class="flex flex-wrap gap-2">
                    <img
                      v-for="(url, i) in (sup.image_url ?? [])"
                      :key="'sup-img-' + i"
                      :src="imgUrl(url)"
                      alt="補件憑證"
                      @click="openLightbox(imgUrl(url))"
                      class="w-14 h-14 object-cover rounded-lg border border-gray-200 cursor-zoom-in hover:opacity-80 transition-opacity"
                    />
                    <img
                      v-for="(url, i) in (sup.item_image_url ?? [])"
                      :key="'sup-item-' + i"
                      :src="imgUrl(url)"
                      alt="補件物品照"
                      @click="openLightbox(imgUrl(url))"
                      class="w-14 h-14 object-cover rounded-lg border border-purple-200 cursor-zoom-in hover:opacity-80 transition-opacity ring-1 ring-purple-300"
                    />
                    <div v-if="!(sup.image_url?.length) && !(sup.item_image_url?.length)" class="text-xs text-gray-300 italic py-2">
                      （無圖片）
                    </div>
                  </div>

                  <!-- 補件操作：只有解除（案件整體確認由底部按鈕處理） -->
                  <div class="flex gap-2 pt-1">
                    <button
                      @click.stop="unlinkSupplement(sup, item.invoice)"
                      :disabled="unlinkingId === sup.id"
                      class="flex items-center gap-1 px-3 py-1.5 border border-gray-300 hover:border-red-300 hover:text-red-500 text-gray-500 text-xs rounded-lg transition-colors disabled:opacity-50"
                      title="解除配對，補件移回孤立補件區"
                    >
                      <Loader2 v-if="unlinkingId === sup.id" :size="12" class="animate-spin" />
                      <Unlink2 v-else :size="12" />
                      解除
                    </button>
                  </div>
                </div>

                <!-- 案件層級確認完成（永遠顯示，讓案件可移出待退貨管理） -->
                <div class="pt-1">
                  <button
                    @click.stop="finalizeCase(item)"
                    :disabled="finalizingInvoiceId === item.invoice.id"
                    class="w-full flex items-center justify-center gap-1.5 px-3 py-2 bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors"
                  >
                    <Loader2 v-if="finalizingInvoiceId === item.invoice.id" :size="12" class="animate-spin" />
                    <CheckCircle2 v-else :size="12" />
                    {{ finalizingInvoiceId === item.invoice.id ? '處理中...' : '確認配對完成' }}
                  </button>
                </div>

                <!-- 拖曳放置區（永遠顯示，支援繼續新增補件） -->
                <div
                  class="flex items-center justify-center h-12 border-2 border-dashed rounded-xl text-xs transition-colors"
                  :class="dragOverInvoiceId === item.invoice.id
                    ? 'border-purple-400 text-purple-400 bg-purple-50'
                    : item.supplements?.length
                      ? 'border-gray-100 text-gray-300'
                      : 'border-gray-200 text-gray-400'"
                >
                  <Link2 :size="13" class="mr-1.5" />
                  {{ item.supplements?.length ? '繼續拖曳補件至此' : '從右欄拖曳補件至此以配對' }}
                </div>
              </div>
            </div>
          </div>
          </div><!-- /flex-1 overflow-y-auto -->
        </div>

        <!-- ── 右欄：補件物品照池 ── -->
        <div class="w-[42%] flex flex-col min-h-0">

          <!-- 搜尋欄 -->
          <div class="shrink-0 px-4 pt-3 pb-2 border-b border-gray-100 space-y-2">
            <p class="text-[11px] font-medium text-gray-500">待配對補件（拖曳至左側憑證以配對）</p>
            <div class="flex gap-1.5">
              <input
                v-model="searchQuery"
                @keyup.enter="searchSupplements"
                placeholder="輸入上傳者姓名搜尋..."
                class="flex-1 text-xs px-2.5 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400 bg-white"
              />
              <button
                @click="searchSupplements"
                :disabled="isSearching"
                class="flex items-center gap-1 px-2.5 py-1.5 bg-purple-500 hover:bg-purple-600 text-white text-xs rounded-lg disabled:opacity-50 transition-colors"
              >
                <Loader2 v-if="isSearching" :size="12" class="animate-spin" />
                <Search v-else :size="12" />
              </button>
              <button
                v-if="searchQuery"
                @click="clearSearch"
                class="px-2 py-1.5 border border-gray-200 text-gray-400 hover:text-gray-600 text-xs rounded-lg transition-colors"
              >×</button>
            </div>
            <p class="text-[10px] text-gray-400">
              {{ searchQuery.trim() ? `搜尋結果（${rightPanelItems.length} 筆）` : `孤立補件（${orphanSupplements.length} 筆）` }}
            </p>
          </div>

          <!-- 補件卡片清單 -->
          <div class="flex-1 overflow-y-auto px-3 py-2 space-y-2">

            <!-- 無資料 -->
            <div v-if="rightPanelItems.length === 0"
              class="flex flex-col items-center justify-center h-full text-gray-300 text-xs gap-2">
              <PackageX :size="28" class="opacity-40" />
              <span v-if="searchQuery.trim()">未找到符合的補件</span>
              <span v-else>目前無孤立補件</span>
            </div>

            <!-- 補件卡片（draggable） -->
            <div
              v-for="sup in rightPanelItems"
              :key="sup.id"
              draggable="true"
              @dragstart="onDragStart($event, sup)"
              @dragend="onDragEnd"
              :class="[
                'bg-white border rounded-xl p-2.5 cursor-grab active:cursor-grabbing select-none transition-all',
                draggingSupplementId === sup.id ? 'opacity-40 border-purple-300' : 'border-gray-200 hover:border-purple-300 hover:shadow-sm',
              ]"
            >
              <!-- 卡片標題 -->
              <div class="flex items-center gap-1.5 mb-1.5">
                <span class="w-1.5 h-1.5 rounded-full shrink-0"
                  :class="STATUS_DOT[sup.status] ?? 'bg-gray-300'" />
                <span class="font-mono text-[11px] font-semibold text-gray-700 truncate">{{ sup.serial_number }}</span>
                <!-- 情境類型 badge -->
                <span v-if="relationTypeLabel(sup.relation_type)"
                  class="text-[9px] px-1 py-0.5 rounded shrink-0 font-medium"
                  :class="{
                    'bg-blue-100 text-blue-600': sup.relation_type === 'VOID_REPLACE',
                    'bg-orange-100 text-orange-600': sup.relation_type === 'CREDIT_NOTE',
                    'bg-purple-100 text-purple-600': sup.relation_type === 'RETURN_SUPPLEMENT',
                  }"
                >{{ relationTypeLabel(sup.relation_type) }}</span>
                <span class="text-[10px] text-gray-400 shrink-0">{{ sup.uploader_name }}</span>
                <button
                  @click.stop="deleteOrphanSupplement(sup)"
                  :disabled="deletingOrphanId === sup.id"
                  class="ml-auto flex items-center justify-center w-5 h-5 rounded hover:bg-red-50 text-gray-300 hover:text-red-400 disabled:opacity-50 transition-colors"
                  title="刪除孤立補件"
                >
                  <Loader2 v-if="deletingOrphanId === sup.id" :size="11" class="animate-spin" />
                  <Trash2 v-else :size="11" />
                </button>
              </div>

              <!-- 建議配對 -->
              <div v-if="sup.suggested_match"
                class="flex items-center gap-1.5 mb-1.5 px-2 py-1 bg-amber-50 border border-amber-200 rounded-lg">
                <span class="text-[9px] text-amber-600 font-medium">✨ 建議配對至 {{ sup.suggested_match.serial_number }}</span>
                <button
                  @click.stop="confirmSuggestedMatch(sup)"
                  :disabled="isLinking"
                  class="ml-auto text-[9px] px-1.5 py-0.5 bg-amber-500 hover:bg-amber-600 text-white rounded disabled:opacity-50 transition-colors"
                >一鍵確認</button>
              </div>

              <!-- 發票資訊列 -->
              <div class="flex flex-wrap gap-x-3 gap-y-0.5 mb-1.5">
                <span v-if="sup.total_amount != null" class="text-[11px] font-medium text-gray-700">
                  NT${{ Number(sup.total_amount).toLocaleString() }}
                </span>
                <span v-if="sup.expense_date" class="text-[10px] text-gray-400">
                  {{ sup.expense_date }}
                </span>
                <span v-if="sup.invoice_number" class="text-[10px] font-mono text-gray-400 truncate">
                  {{ sup.invoice_number }}
                </span>
              </div>

              <!-- 備註 -->
              <div class="mb-1.5 space-y-0.5">
                <p v-if="sup.item_description" class="text-[10px] text-gray-500 truncate"
                  :title="sup.item_description">{{ sup.item_description }}</p>
                <p class="text-[10px] rounded px-1.5 py-1"
                  :class="sup.user_description ? 'bg-amber-50 text-amber-700' : 'text-gray-300 italic'"
                  :title="sup.user_description || ''">
                  {{ sup.user_description || '無備註' }}
                </p>
              </div>

              <!-- 圖片縮圖：image_url（憑證）+ item_image_url（物品照）-->
              <div class="flex flex-wrap gap-1.5">
                <div v-for="(url, i) in (sup.item_image_url ?? [])" :key="'item-'+i"
                  class="relative cursor-zoom-in"
                  @click.stop="openLightbox(imgUrl(url))">
                  <img :src="imgUrl(url)" alt="物品照"
                    class="w-10 h-10 object-cover rounded-lg border border-gray-200 hover:opacity-80 transition-opacity" />
                  <span class="absolute bottom-0 inset-x-0 text-[7px] text-white bg-gray-600 text-center rounded-b-lg">品</span>
                </div>
                <div v-for="(url, i) in (sup.image_url ?? [])" :key="'exp-'+i"
                  class="relative cursor-zoom-in"
                  @click.stop="openLightbox(imgUrl(url))">
                  <img :src="imgUrl(url)" alt="憑證"
                    class="w-10 h-10 object-cover rounded-lg border border-gray-200 hover:opacity-80 transition-opacity" />
                  <span class="absolute bottom-0 inset-x-0 text-[7px] text-white bg-green-600 text-center rounded-b-lg">憑</span>
                </div>
                <div v-if="!(sup.item_image_url?.length) && !(sup.image_url?.length)"
                  class="text-[10px] text-gray-300 italic">（無圖片）</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 配對確認 Dialog -->
    <div v-if="pendingLink"
      class="fixed inset-0 z-[60] bg-black/40 flex items-center justify-center p-4"
      @click.self="pendingLink = null"
    >
      <div class="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <div class="flex items-center gap-2 text-gray-800 font-semibold">
          <Link2 :size="17" class="text-purple-500" />
          確認配對？
        </div>
        <div class="text-sm text-gray-600 space-y-1">
          <p>補件：<span class="font-mono font-medium text-gray-800">{{ pendingLink.supplementSerial }}</span></p>
          <p>↕</p>
          <p>憑證：<span class="font-mono font-medium text-gray-800">{{ pendingLink.invoiceSerial }}</span>
            <span v-if="pendingLink.invoiceNumber" class="text-gray-400 ml-1">（{{ pendingLink.invoiceNumber }}）</span>
          </p>
        </div>
        <p class="text-xs text-gray-400">配對後可展開案件查看補件圖片，也可再次解除配對。</p>
        <div class="flex justify-end gap-2">
          <button @click="pendingLink = null"
            class="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50">
            取消
          </button>
          <button @click="confirmLink" :disabled="isLinking"
            class="px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50">
            {{ isLinking ? '配對中...' : '確定配對' }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 燈箱 -->
  <Teleport to="body">
    <div
      v-if="lightboxUrl"
      class="fixed inset-0 z-[70] bg-black/90 flex items-center justify-center p-4 cursor-zoom-out"
      @click="closeLightbox"
      @keyup.esc="closeLightbox"
      tabindex="0"
    >
      <img
        :src="lightboxUrl"
        alt="圖片預覽"
        class="max-w-full max-h-full object-contain rounded-lg shadow-2xl cursor-default"
        @click.stop
      />
      <button
        @click="closeLightbox"
        class="absolute top-4 right-4 text-white/60 hover:text-white transition-colors"
      >
        <X :size="28" />
      </button>
    </div>
  </Teleport>
</template>
