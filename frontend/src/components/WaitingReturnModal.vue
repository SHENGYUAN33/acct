<script setup>
import { ref, computed, onMounted } from 'vue'
import { X, Loader2, PackageX, CheckCircle2, ChevronRight, ChevronDown, Search, Link2, Unlink2, Trash2 } from 'lucide-vue-next'
import { fetchWaitingReturns, fetchExpenses, updateExpense, deleteExpense, pairExpense } from '../api/expenseApi'
import { toast } from 'vue3-toastify'

const emit = defineEmits(['close', 'count-changed'])

const BACKEND_BASE = 'http://localhost:8000'

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
const completingId = ref(null)
const unlinkingId = ref(null)

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
    const res = await fetchExpenses({ q, page_size: 30 })
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

function addToLeftPanel(expense) {
  cases.value = [{ invoice: expense, supplement: null }, ...cases.value]
  leftSearchQuery.value = ''
  leftSearchResults.value = []
  showLeftSearch.value = false
}

// ── 確認配對完成：補件 → COMPLETED，憑證 → PENDING ────────────────
async function markCompleted(caseItem) {
  const key = caseItem.supplement.id
  if (completingId.value === key) return
  completingId.value = key
  try {
    await Promise.all([
      updateExpense(caseItem.supplement.id, { status: 'COMPLETED' }),
      updateExpense(caseItem.invoice.id, { status: 'PENDING' }),
    ])
    toast.success('配對完成，憑證已移至待審核')
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('操作失敗，請稍後再試')
  } finally {
    completingId.value = null
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
async function unlinkSupplement(supplement) {
  if (unlinkingId.value === supplement.id) return
  unlinkingId.value = supplement.id
  try {
    await updateExpense(supplement.id, {
      referenced_invoice_number: null,
      parent_id: null,
    })
    toast.success(`補件 ${supplement.serial_number} 已解除配對`)
    await loadData()
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

      <!-- Empty -->
      <div v-else-if="cases.length === 0 && orphanSupplements.length === 0"
        class="flex-1 flex flex-col items-center justify-center text-gray-400 gap-3">
        <PackageX :size="40" class="opacity-25" />
        <p class="text-sm font-medium">目前無待退貨案件</p>
        <p class="text-xs text-gray-300">備註含「待退貨」的報帳會顯示於此</p>
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
                  <span v-if="item.supplement && item.supplement.status === 'COMPLETED'"
                    class="text-[10px] bg-teal-100 text-teal-600 px-1.5 py-0.5 rounded">已結清</span>
                  <span v-else-if="item.supplement"
                    class="text-[10px] bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded">已配對</span>
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

                <!-- 有補件 -->
                <div v-if="item.supplement" class="bg-gray-50 rounded-xl border border-gray-200 p-3 space-y-2">
                  <div class="flex items-center gap-1.5">
                    <span class="w-1.5 h-1.5 rounded-full shrink-0"
                      :class="STATUS_DOT[item.supplement.status] ?? 'bg-gray-300'" />
                    <span class="font-mono text-[11px] text-gray-600">{{ item.supplement.serial_number }}</span>
                    <span class="text-[10px] text-gray-400">{{ item.supplement.uploader_name }}</span>
                    <span v-if="item.supplement.status === 'COMPLETED'"
                      class="ml-auto text-[10px] bg-teal-100 text-teal-600 px-1.5 py-0.5 rounded">已結清</span>
                  </div>

                  <!-- 補件圖片 -->
                  <div class="flex flex-wrap gap-2">
                    <div v-for="img in (item.supplement.images ?? [])" :key="img.id"
                      class="relative shrink-0 cursor-zoom-in"
                      @click="openLightbox(imgUrl(img.image_url))">
                      <img :src="imgUrl(img.image_url)" alt="補件圖片"
                        class="w-14 h-14 object-cover rounded-lg border border-gray-200 hover:opacity-80 transition-opacity" />
                      <span
                        :class="img.is_voucher ? 'bg-green-600' : 'bg-gray-600'"
                        class="absolute bottom-0 inset-x-0 text-[8px] text-white text-center rounded-b-lg py-0.5"
                      >{{ img.is_voucher ? '憑證' : '物品照' }}</span>
                    </div>
                    <div v-if="!(item.supplement.images?.length)" class="text-xs text-gray-300 italic py-2">
                      （無圖片）
                    </div>
                  </div>

                  <!-- 動作按鈕（已結清不顯示） -->
                  <div v-if="item.supplement.status !== 'COMPLETED'" class="flex gap-2 pt-1">
                    <button
                      @click.stop="markCompleted(item)"
                      :disabled="completingId === item.supplement.id"
                      class="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors"
                      title="補件標記完成，憑證移至待審核"
                    >
                      <Loader2 v-if="completingId === item.supplement.id" :size="12" class="animate-spin" />
                      <CheckCircle2 v-else :size="12" />
                      {{ completingId === item.supplement.id ? '處理中...' : '確認配對完成' }}
                    </button>
                    <button
                      @click.stop="unlinkSupplement(item.supplement)"
                      :disabled="unlinkingId === item.supplement.id"
                      class="flex items-center gap-1 px-3 py-1.5 border border-gray-300 hover:border-red-300 hover:text-red-500 text-gray-500 text-xs rounded-lg transition-colors disabled:opacity-50"
                      title="解除配對，補件移回孤立補件區"
                    >
                      <Loader2 v-if="unlinkingId === item.supplement.id" :size="12" class="animate-spin" />
                      <Unlink2 v-else :size="12" />
                      解除
                    </button>
                  </div>
                </div>

                <!-- 無補件：提示拖曳 -->
                <div v-else
                  class="flex items-center justify-center h-16 border-2 border-dashed rounded-xl text-xs text-gray-400 transition-colors"
                  :class="dragOverInvoiceId === item.invoice.id ? 'border-purple-400 text-purple-400 bg-purple-50' : 'border-gray-200'"
                >
                  <Link2 :size="14" class="mr-1.5" />
                  從右欄拖曳補件至此以配對
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

              <!-- 備註：item_description + user_description -->
              <p v-if="sup.item_description" class="text-[10px] text-gray-500 truncate mb-0.5"
                :title="sup.item_description">{{ sup.item_description }}</p>
              <p v-if="sup.user_description" class="text-[10px] text-gray-400 italic truncate mb-1.5"
                :title="sup.user_description">{{ sup.user_description }}</p>

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
