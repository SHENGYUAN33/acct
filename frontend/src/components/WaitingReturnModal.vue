<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { X, Loader2, PackageX, CheckCircle2, ChevronRight, ChevronDown, Search, Link2, Unlink2, Trash2, SlidersHorizontal, Plus } from 'lucide-vue-next'
import { getStatusConfig } from '../constants/status.js'
import { getRelationTypeConfig, SUPPLEMENT_RELATION_TYPES, RELATION_TYPE_OPTIONS, EDITABLE_RELATION_TYPES } from '../constants/relationType.js'
import { fetchWaitingReturns, fetchExpenses, fetchRelatedExpenses, updateExpense, pairExpense } from '../api/expenseApi'
import { fetchVoucherCategories, fetchDepartments } from '../api/configApi'
import { toast } from 'vue3-toastify'
import { secureImgUrl as imgUrl, isViewableImage } from '../utils/imageUrl'
import { getVoucherLabel } from '../constants/voucher.js'

const emit = defineEmits(['close', 'count-changed'])

// ── 資料
const isLoading = ref(true)
const cases = ref([])
const orphanSupplements = ref([])

// ── 左欄展開
const expandedInvoiceId = ref(null)

// ── 拖拉配對
const draggingSupplementId = ref(null)
const dragOverInvoiceId = ref(null)
const pendingLink = ref(null)
const isLinking = ref(false)

// ── 動作按鈕
const unlinkingId = ref(null)
const finalizingInvoiceId = ref(null)
const removingCaseId = ref(null)
const deletingOrphanId = ref(null)

// ── 進階篩選選項（動態載入）
const availableDepts = ref([])
const voucherCategoryOptions = ref([])

// ── 工具：voucher_category 比對（相容 JSON 字串或陣列）
function matchesVoucherCat(expense, category) {
  if (!category) return true
  const cats = Array.isArray(expense.voucher_categories)
    ? expense.voucher_categories
    : JSON.parse(expense.voucher_categories || '[]')
  return cats.includes(category)
}

// ── 左欄：前端即時篩選
const showLeftFilter = ref(false)
const leftFilter = reactive({
  serial_number: '', invoice_number: '', uploader_name: '',
  uploader_dept: '', date_from: '', date_to: '',
  amount_min: '', amount_max: '', voucher_category: '',
})
const leftActiveCount = computed(() => Object.values(leftFilter).filter(v => v !== '').length)

const filteredCases = computed(() => {
  if (leftActiveCount.value === 0) return cases.value
  return cases.value.filter(item => {
    const inv = item.invoice
    if (leftFilter.serial_number && !inv.serial_number?.includes(leftFilter.serial_number)) return false
    if (leftFilter.invoice_number && !inv.invoice_number?.includes(leftFilter.invoice_number)) return false
    if (leftFilter.uploader_name && !inv.uploader_name?.includes(leftFilter.uploader_name)) return false
    if (leftFilter.uploader_dept && inv.uploader_dept !== leftFilter.uploader_dept) return false
    if (leftFilter.date_from && inv.upload_date && inv.upload_date.slice(0, 10) < leftFilter.date_from) return false
    if (leftFilter.date_to && inv.upload_date && inv.upload_date.slice(0, 10) > leftFilter.date_to) return false
    if (leftFilter.amount_min !== '' && Number(inv.total_amount) < Number(leftFilter.amount_min)) return false
    if (leftFilter.amount_max !== '' && Number(inv.total_amount) > Number(leftFilter.amount_max)) return false
    if (leftFilter.voucher_category && !matchesVoucherCat(inv, leftFilter.voucher_category)) return false
    return true
  })
})

function clearLeftFilter() {
  Object.keys(leftFilter).forEach(k => { leftFilter[k] = '' })
}

// ── 左欄：新增（搜尋 DB → 加入待退貨）
const showLeftAdd = ref(false)
const leftAddQuery = ref('')
const isLeftAdding = ref(false)
const leftAddResults = ref([])

async function searchForLeftAdd() {
  const q = leftAddQuery.value.trim()
  if (!q) { leftAddResults.value = []; return }
  isLeftAdding.value = true
  try {
    const res = await fetchExpenses({ q, page_size: 10 })
    const existingIds = new Set(cases.value.map(c => c.invoice.id))
    leftAddResults.value = (res.data?.data?.items ?? []).filter(e => !existingIds.has(e.id))
  } catch {
    toast.error('搜尋失敗')
    leftAddResults.value = []
  } finally {
    isLeftAdding.value = false
  }
}

async function addToLeftPanel(expense) {
  if (expense.status !== 'WAITING_RETURN') {
    try {
      await updateExpense(expense.id, { status: 'WAITING_RETURN' })
      expense = { ...expense, status: 'WAITING_RETURN' }
    } catch {
      toast.error('無法將該憑證標記為待退貨，請稍後再試')
      return
    }
  }
  let existingSupplements = []
  try {
    const res = await fetchRelatedExpenses(expense.id)
    existingSupplements = (res.data?.data ?? [])
      .filter(e => SUPPLEMENT_RELATION_TYPES.includes(e.relation_type))
  } catch { }
  cases.value = [{ invoice: expense, supplements: existingSupplements }, ...cases.value]
  leftAddQuery.value = ''
  leftAddResults.value = []
  showLeftAdd.value = false
  emit('count-changed')
}

// ── 左欄：移出待退貨（解除補件關聯，invoice 改回 PENDING）
async function removeFromWaitingReturn(item) {
  const invoice = item.invoice
  if (removingCaseId.value === invoice.id) return
  if (!confirm(`確定將 ${invoice.serial_number} 移出待退貨管理？\n已配對的補件將解除關聯，費用資料仍會保留。`)) return
  removingCaseId.value = invoice.id
  try {
    const ops = []
    for (const sup of (item.supplements ?? [])) {
      ops.push(updateExpense(sup.id, { parent_id: null, referenced_invoice_number: null }))
    }
    ops.push(updateExpense(invoice.id, { status: 'PENDING', relation_type: null }))
    await Promise.all(ops)
    toast.success(`${invoice.serial_number} 已移出待退貨管理`)
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('操作失敗，請稍後再試')
  } finally {
    removingCaseId.value = null
  }
}

// ── 右欄：前端即時篩選
const showRightFilter = ref(false)
const rightFilter = reactive({
  serial_number: '', invoice_number: '', uploader_name: '',
  uploader_dept: '', date_from: '', date_to: '',
  amount_min: '', amount_max: '', voucher_category: '',
})
const rightActiveCount = computed(() => Object.values(rightFilter).filter(v => v !== '').length)

const filteredOrphanSupplements = computed(() => {
  if (rightActiveCount.value === 0) return orphanSupplements.value
  return orphanSupplements.value.filter(sup => {
    if (rightFilter.serial_number && !sup.serial_number?.includes(rightFilter.serial_number)) return false
    if (rightFilter.invoice_number && !sup.invoice_number?.includes(rightFilter.invoice_number)) return false
    if (rightFilter.uploader_name && !sup.uploader_name?.includes(rightFilter.uploader_name)) return false
    if (rightFilter.uploader_dept && sup.uploader_dept !== rightFilter.uploader_dept) return false
    if (rightFilter.date_from && sup.upload_date && sup.upload_date.slice(0, 10) < rightFilter.date_from) return false
    if (rightFilter.date_to && sup.upload_date && sup.upload_date.slice(0, 10) > rightFilter.date_to) return false
    if (rightFilter.amount_min !== '' && Number(sup.total_amount) < Number(rightFilter.amount_min)) return false
    if (rightFilter.amount_max !== '' && Number(sup.total_amount) > Number(rightFilter.amount_max)) return false
    if (rightFilter.voucher_category && !matchesVoucherCat(sup, rightFilter.voucher_category)) return false
    return true
  })
})

function clearRightFilter() {
  Object.keys(rightFilter).forEach(k => { rightFilter[k] = '' })
}

// ── 右欄：新增（搜尋 DB → 自動判斷 relation_type → 加入補件池）
const showRightAdd = ref(false)
const rightAddQuery = ref('')
const isRightAdding = ref(false)
const rightAddResults = ref([])

function autoDetectRelationType(expense) {
  // 1. 已有明確的補件 relation_type → 直接沿用
  if (expense.relation_type && SUPPLEMENT_RELATION_TYPES.includes(expense.relation_type)) {
    return expense.relation_type
  }
  // 2. OCR 辨識到 voucher_category = CREDIT_NOTE → 折讓單（比關鍵字更可靠）
  const cats = Array.isArray(expense.voucher_categories)
    ? expense.voucher_categories
    : JSON.parse(expense.voucher_categories || '[]')
  if (cats.includes('CREDIT_NOTE')) return 'CREDIT_NOTE'
  // 3. 說明文字格式或關鍵字
  const desc = expense.user_description || ''
  if (/(?:之前收據|補差額|差額補足|原單).*日期\s*[：:]\s*\d{4}-\d{2}-\d{2}.*金額\s*[：:]\s*\d/.test(desc)) return 'RETURN_SUPPLEMENT'
  const descLower = desc.toLowerCase()
  if (descLower.includes('換單') || descLower.includes('換發票')) return 'VOID_REPLACE'
  if (descLower.includes('折讓')) return 'CREDIT_NOTE'
  return 'RETURN_SUPPLEMENT'
}

async function searchForRightAdd() {
  const q = rightAddQuery.value.trim()
  if (!q) { rightAddResults.value = []; return }
  isRightAdding.value = true
  try {
    const res = await fetchExpenses({ q, page_size: 10 })
    const orphanIds = new Set(orphanSupplements.value.map(s => s.id))
    const pairedIds = new Set(cases.value.flatMap(c => (c.supplements ?? []).map(s => s.id)))
    const invoiceIds = new Set(cases.value.map(c => c.invoice.id))
    rightAddResults.value = (res.data?.data?.items ?? []).filter(e =>
      !orphanIds.has(e.id) && !pairedIds.has(e.id) && !invoiceIds.has(e.id)
    )
  } catch {
    toast.error('搜尋失敗')
    rightAddResults.value = []
  } finally {
    isRightAdding.value = false
  }
}

async function addToRightPanel(expense) {
  const relationType = autoDetectRelationType(expense)
  const payload = { relation_type: relationType, dismissed_from_waiting_return: false }
  if (SUPPLEMENT_RELATION_TYPES.includes(relationType)) payload.voucher_categories = JSON.stringify(['RETURN'])
  try {
    await updateExpense(expense.id, payload)
    rightAddQuery.value = ''
    rightAddResults.value = []
    showRightAdd.value = false
    toast.success(`${expense.serial_number} 已加入補件池（${relationTypeLabel(relationType)}）`)
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('加入失敗，請稍後再試')
  }
}

// ── 情境類型 inline 下拉（右欄補件卡片）
const relationTypeDropdownId = ref(null)
const updatingRelTypeId = ref(null)
const dropdownPos = ref({ top: 0, left: 0 })
const dropdownExpense = ref(null)

function openRelTypeDropdown(event, sup) {
  if (relationTypeDropdownId.value === sup.id) {
    relationTypeDropdownId.value = null
    dropdownExpense.value = null
    return
  }
  const rect = event.currentTarget.getBoundingClientRect()
  dropdownPos.value = { top: rect.bottom + 2, left: rect.left }
  dropdownExpense.value = sup
  relationTypeDropdownId.value = sup.id
}

async function changeRelationType(sup, newType) {
  relationTypeDropdownId.value = null
  if (newType === sup.relation_type) return
  updatingRelTypeId.value = sup.id
  try {
    const baseUpdate = { relation_type: newType, dismissed_from_waiting_return: false }
    if (SUPPLEMENT_RELATION_TYPES.includes(newType)) {
      baseUpdate.voucher_categories = JSON.stringify(['RETURN'])
    }
    await updateExpense(sup.id, baseUpdate)
    toast.success('補件類型已更新')
    await loadData()
  } catch {
    toast.error('更新失敗，請稍後再試')
  } finally {
    updatingRelTypeId.value = null
  }
}

// ── 燈箱
const lightboxUrl = ref(null)
function openLightbox(url) { lightboxUrl.value = url }
function closeLightbox() { lightboxUrl.value = null }

// ── 載入
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

async function loadAvailableDepts() {
  try {
    const res = await fetchDepartments()
    availableDepts.value = res.data?.data?.departments ?? []
  } catch { }
}
onMounted(loadAvailableDepts)

async function loadVoucherCategories() {
  try {
    const res = await fetchVoucherCategories()
    voucherCategoryOptions.value = res.data?.data?.voucher_categories ?? []
  } catch { }
}
onMounted(loadVoucherCategories)

// ── 左欄手風琴
function toggleExpand(invoiceId) {
  expandedInvoiceId.value = expandedInvoiceId.value === invoiceId ? null : invoiceId
}

// ── 拖拉
function onDragStart(event, supplement) {
  draggingSupplementId.value = supplement.id
  event.dataTransfer.effectAllowed = 'link'
  event.dataTransfer.setData('text/plain', supplement.id)
}

function onDragEnd() {
  draggingSupplementId.value = null
  dragOverInvoiceId.value = null
}

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
  const supplement = orphanSupplements.value.find(s => s.id === draggingSupplementId.value)
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

// ── 確認配對
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

// ── 一鍵建議配對
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

// ── 情境類型標籤（從 SSOT 取得）
function relationTypeLabel(type) {
  return getRelationTypeConfig(type)?.label ?? ''
}

// ── 案件確認完成
async function finalizeCase(item) {
  const invoice = item.invoice
  if (finalizingInvoiceId.value === invoice.id) return
  finalizingInvoiceId.value = invoice.id
  try {
    const ops = []
    const hasVoidReplace = item.supplements?.some(s => s.relation_type === 'VOID_REPLACE')
    for (const sup of (item.supplements ?? [])) {
      if (!sup.parent_id) ops.push(pairExpense(sup.id, invoice.id))
      if (sup.status !== 'PENDING') ops.push(updateExpense(sup.id, { status: 'PENDING' }))
    }
    if (hasVoidReplace) {
      ops.push(updateExpense(invoice.id, { status: 'PENDING', relation_type: 'VOID_ORIGINAL' }))
    } else {
      ops.push(updateExpense(invoice.id, { status: 'PENDING' }))
    }
    await Promise.all(ops)
    toast.success(hasVoidReplace ? '換單完成，原始憑證已標記為沖銷' : '案件已完成，憑證移至待審核')
    await loadData()
    emit('count-changed')
  } catch {
    toast.error('操作失敗，請稍後再試')
  } finally {
    finalizingInvoiceId.value = null
  }
}

// ── 移出孤立補件
async function deleteOrphanSupplement(sup) {
  if (deletingOrphanId.value === sup.id) return
  if (!confirm(`確定將 ${sup.serial_number} 移出待退貨管理？\n費用資料仍會保留，在主頁面可繼續查看。`)) return
  deletingOrphanId.value = sup.id
  try {
    await updateExpense(sup.id, { dismissed_from_waiting_return: true })
    toast.success(`${sup.serial_number} 已移出待退貨管理`)
    await loadData()
    emit('count-changed')
  } catch (err) {
    toast.error(err?.response?.data?.detail || '操作失敗，請稍後再試')
  } finally {
    deletingOrphanId.value = null
  }
}

// ── 解除配對
async function unlinkSupplement(supplement, invoice) {
  if (unlinkingId.value === supplement.id) return
  unlinkingId.value = supplement.id
  try {
    const ops = [
      updateExpense(supplement.id, { parent_id: null, referenced_invoice_number: null }),
    ]
    // 解除配對後，原始憑證回到待退貨（WAITING_RETURN）並清除沖銷標記
    if (invoice) {
      ops.push(updateExpense(invoice.id, { status: 'WAITING_RETURN', relation_type: null }))
    }
    await Promise.all(ops)
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
          <span v-if="!isLoading" class="text-xs text-gray-400 ml-1">
            {{ cases.length }} 筆待退貨案件
            <span v-if="leftActiveCount > 0" class="text-purple-500">（顯示 {{ filteredCases.length }} 筆）</span>
          </span>
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

          <!-- Toolbar: 篩選 + 新增 -->
          <div class="shrink-0 px-3 py-2 border-b border-gray-100 relative">
            <div class="flex items-center gap-1.5 flex-wrap min-h-[28px]">

              <!-- 篩選按鈕 -->
              <button
                @click="showLeftFilter = !showLeftFilter; showLeftAdd = false"
                class="flex items-center gap-1 px-2 py-1 text-xs border rounded-lg transition-colors shrink-0"
                :class="showLeftFilter || leftActiveCount > 0
                  ? 'border-purple-300 bg-purple-50 text-purple-600'
                  : 'border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600'"
              >
                <SlidersHorizontal :size="11" />
                <span>篩選</span>
                <span v-if="leftActiveCount > 0"
                  class="ml-0.5 inline-flex items-center justify-center w-4 h-4 bg-purple-500 text-white rounded-full text-[9px] font-bold">
                  {{ leftActiveCount }}
                </span>
              </button>

              <!-- 新增按鈕 -->
              <button
                @click="showLeftAdd = !showLeftAdd; showLeftFilter = false"
                class="flex items-center gap-1 px-2 py-1 text-xs border rounded-lg transition-colors shrink-0"
                :class="showLeftAdd
                  ? 'border-teal-300 bg-teal-50 text-teal-600'
                  : 'border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600'"
              >
                <Plus :size="11" />
                <span>新增</span>
              </button>

              <!-- Active filter chips -->
              <span v-if="leftFilter.serial_number"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                EXP: {{ leftFilter.serial_number }}
                <button @click="leftFilter.serial_number = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="leftFilter.invoice_number"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                發票: {{ leftFilter.invoice_number }}
                <button @click="leftFilter.invoice_number = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="leftFilter.uploader_name"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ leftFilter.uploader_name }}
                <button @click="leftFilter.uploader_name = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="leftFilter.uploader_dept"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ leftFilter.uploader_dept }}
                <button @click="leftFilter.uploader_dept = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="leftFilter.date_from || leftFilter.date_to"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ leftFilter.date_from || '起' }} ～ {{ leftFilter.date_to || '今' }}
                <button @click="leftFilter.date_from = ''; leftFilter.date_to = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="leftFilter.amount_min !== '' || leftFilter.amount_max !== ''"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                NT${{ leftFilter.amount_min || '0' }}～{{ leftFilter.amount_max || '∞' }}
                <button @click="leftFilter.amount_min = ''; leftFilter.amount_max = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="leftFilter.voucher_category"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ getVoucherLabel(leftFilter.voucher_category) }}
                <button @click="leftFilter.voucher_category = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <button v-if="leftActiveCount > 0" @click="clearLeftFilter"
                class="text-[10px] text-gray-400 hover:text-gray-600 ml-auto shrink-0">
                清除全部
              </button>
            </div>

            <!-- 左欄篩選 Popover（即時過濾，無需套用按鈕） -->
            <div v-if="showLeftFilter"
              class="absolute left-0 top-full mt-1 z-30 w-72 bg-white border border-gray-200 rounded-xl shadow-xl p-3 space-y-1.5">
              <div class="grid grid-cols-2 gap-1">
                <input v-model="leftFilter.serial_number" placeholder="EXP編號"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <input v-model="leftFilter.invoice_number" placeholder="發票號碼"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
              </div>
              <div class="grid grid-cols-2 gap-1">
                <input v-model="leftFilter.uploader_name" placeholder="上傳者姓名"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <select v-model="leftFilter.uploader_dept"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400 bg-white">
                  <option value="">全部組別</option>
                  <option v-for="dept in availableDepts" :key="dept" :value="dept">{{ dept }}</option>
                </select>
              </div>
              <div class="flex items-center gap-1">
                <input type="date" v-model="leftFilter.date_from"
                  class="flex-1 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <span class="text-gray-400 text-xs shrink-0">～</span>
                <input type="date" v-model="leftFilter.date_to"
                  class="flex-1 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
              </div>
              <div class="flex items-center gap-1">
                <input type="number" v-model="leftFilter.amount_min" placeholder="最低金額"
                  class="flex-1 min-w-0 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <span class="text-gray-400 text-xs shrink-0">～</span>
                <input type="number" v-model="leftFilter.amount_max" placeholder="最高金額"
                  class="flex-1 min-w-0 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <span class="text-gray-400 text-[10px] shrink-0">NT$</span>
              </div>
              <select v-model="leftFilter.voucher_category"
                class="w-full text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400 bg-white">
                <option value="">全部憑證類別</option>
                <option v-for="cat in voucherCategoryOptions" :key="cat.key" :value="cat.key">{{ cat.label }}</option>
              </select>
              <div class="flex gap-1 pt-0.5">
                <button @click="showLeftFilter = false"
                  class="flex-1 px-2.5 py-1.5 bg-purple-500 hover:bg-purple-600 text-white text-xs rounded-lg transition-colors">
                  套用
                </button>
                <button @click="clearLeftFilter(); showLeftFilter = false"
                  class="px-2.5 py-1.5 border border-gray-200 text-gray-400 hover:text-gray-600 text-xs rounded-lg transition-colors">
                  清除
                </button>
              </div>
            </div>

            <!-- 左欄新增 Panel -->
            <div v-if="showLeftAdd" class="mt-1.5">
              <div class="flex gap-1">
                <input
                  v-model="leftAddQuery"
                  @keyup.enter="searchForLeftAdd"
                  placeholder="輸入案件編號或關鍵字..."
                  class="flex-1 text-xs px-2.5 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-teal-400"
                />
                <button @click="searchForLeftAdd" :disabled="isLeftAdding"
                  class="flex items-center gap-1 px-2.5 py-1.5 bg-teal-500 hover:bg-teal-600 text-white text-xs rounded-lg disabled:opacity-50 transition-colors shrink-0">
                  <Loader2 v-if="isLeftAdding" :size="11" class="animate-spin" />
                  <Search v-else :size="11" />
                </button>
              </div>
              <div v-if="leftAddResults.length"
                class="mt-1 bg-white border border-gray-200 rounded-lg overflow-hidden max-h-36 overflow-y-auto">
                <div v-for="exp in leftAddResults" :key="exp.id"
                  @click="addToLeftPanel(exp)"
                  class="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-teal-50 border-b border-gray-100 last:border-0">
                  <span class="font-mono text-[11px] text-gray-800">{{ exp.serial_number }}</span>
                  <span v-if="exp.invoice_number" class="text-[10px] font-mono text-gray-400">{{ exp.invoice_number }}</span>
                  <span class="text-[10px] text-gray-500 truncate">{{ exp.uploader_name }}</span>
                  <span v-if="exp.total_amount != null" class="text-[10px] text-gray-500 shrink-0">
                    NT${{ Number(exp.total_amount).toLocaleString() }}
                  </span>
                  <span class="ml-auto text-[10px] bg-teal-100 text-teal-600 px-1.5 py-0.5 rounded shrink-0">加入</span>
                </div>
              </div>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto">
            <!-- 空狀態 -->
            <div v-if="filteredCases.length === 0"
              class="flex flex-col items-center justify-center h-full text-gray-300 text-xs gap-2 pb-8">
              <PackageX :size="32" class="opacity-30" />
              <span v-if="leftActiveCount > 0" class="text-gray-400 text-sm font-medium">未找到符合的費用</span>
              <span v-else class="text-gray-400 text-sm font-medium">目前無待退貨案件</span>
              <span v-if="leftActiveCount === 0" class="text-gray-300">備註含「待退貨」的報帳會顯示於此</span>
            </div>

            <div class="divide-y divide-gray-100">
              <div
                v-for="item in filteredCases"
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
                  <component
                    :is="expandedInvoiceId === item.invoice.id ? ChevronDown : ChevronRight"
                    :size="15" class="text-gray-400 shrink-0"
                  />
                  <span class="w-2 h-2 rounded-full shrink-0"
                    :class="getStatusConfig(item.invoice.status).dot" />
                  <span class="font-mono text-xs font-semibold text-gray-800">{{ item.invoice.serial_number }}</span>
                  <span v-if="item.invoice.total_amount != null" class="text-xs text-gray-500">
                    NT${{ Number(item.invoice.total_amount).toLocaleString() }}
                  </span>
                  <span v-if="item.invoice.invoice_number" class="text-[11px] font-mono text-gray-400 truncate">
                    {{ item.invoice.invoice_number }}
                  </span>
                  <div class="ml-auto flex items-center gap-1.5 shrink-0">
                    <span v-if="item.supplements?.length > 0"
                      class="text-[10px] bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded">
                      已配對{{ item.supplements.length > 1 ? ` (${item.supplements.length})` : '' }}
                    </span>
                    <span v-else class="text-[10px] bg-orange-100 text-orange-500 px-1.5 py-0.5 rounded">待配對</span>
                    <span v-if="dragOverInvoiceId === item.invoice.id"
                      class="text-[10px] bg-purple-100 text-purple-600 px-2 py-0.5 rounded animate-pulse">
                      放開以配對
                    </span>
                    <!-- 移出待退貨管理 -->
                    <button
                      @click.stop="removeFromWaitingReturn(item)"
                      :disabled="removingCaseId === item.invoice.id"
                      class="flex items-center justify-center w-5 h-5 rounded hover:bg-red-50 text-gray-300 hover:text-red-400 disabled:opacity-50 transition-colors"
                      title="移出待退貨管理"
                    >
                      <Loader2 v-if="removingCaseId === item.invoice.id" :size="11" class="animate-spin" />
                      <Trash2 v-else :size="11" />
                    </button>
                  </div>
                </div>

                <!-- 展開區：補件 + 按鈕 -->
                <div v-if="expandedInvoiceId === item.invoice.id" class="px-4 pb-4 space-y-3">
                  <!-- 原始憑證照片 -->
                  <div>
                    <p class="text-[10px] text-gray-400 mb-1.5 font-medium">原始憑證照片</p>
                    <div class="flex flex-wrap gap-2">
                      <img
                        v-for="(url, i) in (item.invoice.image_url ?? [])"
                        :key="'inv-img-'+i"
                        :src="imgUrl(url)" alt="憑證照片"
                        @click="openLightbox(imgUrl(url))"
                        class="w-14 h-14 object-cover rounded-lg border border-gray-200 cursor-zoom-in hover:opacity-80 transition-opacity"
                      />
                      <span v-if="!(item.invoice.image_url?.length)" class="text-xs text-gray-300 italic py-2">（無原始照片）</span>
                    </div>
                  </div>

                  <!-- 已配對的補件 -->
                  <div
                    v-for="sup in (item.supplements ?? [])"
                    :key="sup.id"
                    class="bg-gray-50 rounded-xl border border-gray-200 p-3 space-y-2"
                  >
                    <div class="flex items-center gap-1.5">
                      <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="getStatusConfig(sup.status).dot" />
                      <span class="font-mono text-[11px] text-gray-600">{{ sup.serial_number }}</span>
                      <span class="text-[10px] text-gray-400">{{ sup.uploader_name }}</span>
                    </div>
                    <div class="flex flex-wrap gap-2">
                      <img v-for="(url, i) in (sup.image_url ?? [])" :key="'sup-img-'+i"
                        :src="imgUrl(url)" alt="補件憑證"
                        @click="openLightbox(imgUrl(url))"
                        class="w-14 h-14 object-cover rounded-lg border border-gray-200 cursor-zoom-in hover:opacity-80 transition-opacity"
                      />
                      <img v-for="(url, i) in (sup.item_image_url ?? [])" :key="'sup-item-'+i"
                        :src="imgUrl(url)" alt="補件物品照"
                        @click="openLightbox(imgUrl(url))"
                        class="w-14 h-14 object-cover rounded-lg border border-purple-200 cursor-zoom-in hover:opacity-80 transition-opacity ring-1 ring-purple-300"
                      />
                      <div v-if="!(sup.image_url?.length) && !(sup.item_image_url?.length)" class="text-xs text-gray-300 italic py-2">（無圖片）</div>
                    </div>
                    <div class="flex gap-2 pt-1">
                      <button
                        @click.stop="unlinkSupplement(sup, item.invoice)"
                        :disabled="unlinkingId === sup.id"
                        class="flex items-center gap-1 px-3 py-1.5 border border-gray-300 hover:border-red-300 hover:text-red-500 text-gray-500 text-xs rounded-lg transition-colors disabled:opacity-50"
                      >
                        <Loader2 v-if="unlinkingId === sup.id" :size="12" class="animate-spin" />
                        <Unlink2 v-else :size="12" />
                        解除
                      </button>
                    </div>
                  </div>

                  <!-- 確認完成 -->
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

                  <!-- 拖曳放置區 -->
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
          </div>
        </div>

        <!-- ── 右欄：補件池 ── -->
        <div class="w-[42%] flex flex-col min-h-0">

          <!-- 右欄 Toolbar -->
          <div class="shrink-0 px-4 pt-3 pb-2 border-b border-gray-100 relative">
            <div class="flex items-start justify-between gap-2 mb-1.5">
              <div>
                <p class="text-[11px] font-medium text-gray-600">
                  待配對補件
                  <span class="font-normal text-gray-300 ml-0.5">— 拖曳至左側憑證以配對</span>
                </p>
                <p class="text-[10px] text-gray-400 mt-0.5">
                  孤立補件（{{ orphanSupplements.length }} 筆）
                  <span v-if="rightActiveCount > 0" class="text-purple-500">— 顯示 {{ filteredOrphanSupplements.length }} 筆</span>
                </p>
              </div>
              <div class="flex items-center gap-1 shrink-0">
                <!-- 新增按鈕 -->
                <button
                  @click="showRightAdd = !showRightAdd; showRightFilter = false"
                  class="flex items-center gap-1 px-2 py-1 text-xs border rounded-lg transition-colors"
                  :class="showRightAdd
                    ? 'border-teal-300 bg-teal-50 text-teal-600'
                    : 'border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600'"
                >
                  <Plus :size="11" />
                  <span>新增</span>
                </button>
                <!-- 篩選按鈕 -->
                <button
                  @click="showRightFilter = !showRightFilter; showRightAdd = false"
                  class="flex items-center gap-1 px-2 py-1 text-xs border rounded-lg transition-colors"
                  :class="showRightFilter || rightActiveCount > 0
                    ? 'border-purple-300 bg-purple-50 text-purple-600'
                    : 'border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600'"
                >
                  <SlidersHorizontal :size="11" />
                  <span>篩選</span>
                  <span v-if="rightActiveCount > 0"
                    class="ml-0.5 inline-flex items-center justify-center w-4 h-4 bg-purple-500 text-white rounded-full text-[9px] font-bold">
                    {{ rightActiveCount }}
                  </span>
                </button>
              </div>
            </div>

            <!-- Active chips for right filter -->
            <div v-if="rightActiveCount > 0" class="flex flex-wrap gap-1">
              <span v-if="rightFilter.serial_number"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                EXP: {{ rightFilter.serial_number }}
                <button @click="rightFilter.serial_number = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="rightFilter.invoice_number"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                發票: {{ rightFilter.invoice_number }}
                <button @click="rightFilter.invoice_number = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="rightFilter.uploader_name"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ rightFilter.uploader_name }}
                <button @click="rightFilter.uploader_name = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="rightFilter.uploader_dept"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ rightFilter.uploader_dept }}
                <button @click="rightFilter.uploader_dept = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="rightFilter.date_from || rightFilter.date_to"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ rightFilter.date_from || '起' }} ～ {{ rightFilter.date_to || '今' }}
                <button @click="rightFilter.date_from = ''; rightFilter.date_to = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="rightFilter.amount_min !== '' || rightFilter.amount_max !== ''"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                NT${{ rightFilter.amount_min || '0' }}～{{ rightFilter.amount_max || '∞' }}
                <button @click="rightFilter.amount_min = ''; rightFilter.amount_max = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <span v-if="rightFilter.voucher_category"
                class="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 border border-purple-200 text-purple-700 text-[10px] rounded-full">
                {{ getVoucherLabel(rightFilter.voucher_category) }}
                <button @click="rightFilter.voucher_category = ''" class="ml-0.5 hover:text-purple-900">×</button>
              </span>
              <button @click="clearRightFilter" class="text-[10px] text-gray-400 hover:text-gray-600 ml-auto shrink-0">
                清除全部
              </button>
            </div>

            <!-- 右欄新增 Panel -->
            <div v-if="showRightAdd" class="mt-1.5">
              <div class="flex gap-1">
                <input
                  v-model="rightAddQuery"
                  @keyup.enter="searchForRightAdd"
                  placeholder="輸入案件編號或關鍵字..."
                  class="flex-1 text-xs px-2.5 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-teal-400"
                />
                <button @click="searchForRightAdd" :disabled="isRightAdding"
                  class="flex items-center gap-1 px-2.5 py-1.5 bg-teal-500 hover:bg-teal-600 text-white text-xs rounded-lg disabled:opacity-50 transition-colors shrink-0">
                  <Loader2 v-if="isRightAdding" :size="11" class="animate-spin" />
                  <Search v-else :size="11" />
                </button>
              </div>
              <div v-if="rightAddResults.length"
                class="mt-1 bg-white border border-gray-200 rounded-lg overflow-hidden max-h-36 overflow-y-auto">
                <div v-for="exp in rightAddResults" :key="exp.id"
                  @click="addToRightPanel(exp)"
                  class="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-teal-50 border-b border-gray-100 last:border-0">
                  <span class="font-mono text-[11px] text-gray-800">{{ exp.serial_number }}</span>
                  <span v-if="exp.invoice_number" class="text-[10px] font-mono text-gray-400">{{ exp.invoice_number }}</span>
                  <span class="text-[10px] text-gray-500 truncate">{{ exp.uploader_name }}</span>
                  <span v-if="exp.total_amount != null" class="text-[10px] text-gray-500 shrink-0">
                    NT${{ Number(exp.total_amount).toLocaleString() }}
                  </span>
                  <span class="text-[9px] text-gray-400 shrink-0">{{ relationTypeLabel(autoDetectRelationType(exp)) }}</span>
                  <span class="ml-auto text-[10px] bg-teal-100 text-teal-600 px-1.5 py-0.5 rounded shrink-0">加入</span>
                </div>
              </div>
            </div>

            <!-- 右欄篩選 Popover -->
            <div v-if="showRightFilter"
              class="absolute right-4 top-full mt-1 z-30 w-72 bg-white border border-gray-200 rounded-xl shadow-xl p-3 space-y-1.5">
              <div class="grid grid-cols-2 gap-1">
                <input v-model="rightFilter.serial_number" placeholder="EXP編號"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <input v-model="rightFilter.invoice_number" placeholder="發票號碼"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
              </div>
              <div class="grid grid-cols-2 gap-1">
                <input v-model="rightFilter.uploader_name" placeholder="上傳者姓名"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <select v-model="rightFilter.uploader_dept"
                  class="text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400 bg-white">
                  <option value="">全部組別</option>
                  <option v-for="dept in availableDepts" :key="dept" :value="dept">{{ dept }}</option>
                </select>
              </div>
              <div class="flex items-center gap-1">
                <input type="date" v-model="rightFilter.date_from"
                  class="flex-1 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <span class="text-gray-400 text-xs shrink-0">～</span>
                <input type="date" v-model="rightFilter.date_to"
                  class="flex-1 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
              </div>
              <div class="flex items-center gap-1">
                <input type="number" v-model="rightFilter.amount_min" placeholder="最低金額"
                  class="flex-1 min-w-0 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <span class="text-gray-400 text-xs shrink-0">～</span>
                <input type="number" v-model="rightFilter.amount_max" placeholder="最高金額"
                  class="flex-1 min-w-0 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400" />
                <span class="text-gray-400 text-[10px] shrink-0">NT$</span>
              </div>
              <select v-model="rightFilter.voucher_category"
                class="w-full text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:border-purple-400 bg-white">
                <option value="">全部憑證類別</option>
                <option v-for="cat in voucherCategoryOptions" :key="cat.key" :value="cat.key">{{ cat.label }}</option>
              </select>
              <div class="flex gap-1 pt-0.5">
                <button @click="showRightFilter = false"
                  class="flex-1 px-2.5 py-1.5 bg-purple-500 hover:bg-purple-600 text-white text-xs rounded-lg transition-colors">
                  套用
                </button>
                <button @click="clearRightFilter(); showRightFilter = false"
                  class="px-2.5 py-1.5 border border-gray-200 text-gray-400 hover:text-gray-600 text-xs rounded-lg transition-colors">
                  清除
                </button>
              </div>
            </div>
          </div>

          <!-- 補件卡片清單 -->
          <div class="flex-1 overflow-y-auto px-3 py-2 space-y-2">
            <div v-if="filteredOrphanSupplements.length === 0"
              class="flex flex-col items-center justify-center h-full text-gray-300 text-xs gap-2">
              <PackageX :size="28" class="opacity-40" />
              <span v-if="rightActiveCount > 0">未找到符合的費用</span>
              <span v-else>目前無孤立補件</span>
            </div>

            <div
              v-for="sup in filteredOrphanSupplements"
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
                <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="getStatusConfig(sup.status).dot" />
                <span class="font-mono text-[11px] font-semibold text-gray-700 truncate">{{ sup.serial_number }}</span>
                <button
                  v-if="EDITABLE_RELATION_TYPES.includes(sup.relation_type)"
                  @click.stop="openRelTypeDropdown($event, sup)"
                  :disabled="updatingRelTypeId === sup.id"
                  class="text-[9px] px-1 py-0.5 rounded shrink-0 font-medium border cursor-pointer hover:opacity-75 transition-opacity disabled:opacity-50 flex items-center gap-0.5"
                  :class="getRelationTypeConfig(sup.relation_type)?.badgeClass"
                  title="點擊可修改補件類型"
                >
                  <Loader2 v-if="updatingRelTypeId === sup.id" :size="9" class="animate-spin" />
                  <template v-else>
                    {{ getRelationTypeConfig(sup.relation_type)?.label }}
                    <span class="opacity-50 text-[8px]">▾</span>
                  </template>
                </button>
                <span
                  v-else-if="relationTypeLabel(sup.relation_type)"
                  class="text-[9px] px-1 py-0.5 rounded shrink-0 font-medium border"
                  :class="getRelationTypeConfig(sup.relation_type)?.badgeClass"
                >{{ relationTypeLabel(sup.relation_type) }}</span>
                <span class="text-[10px] text-gray-400 shrink-0">{{ sup.uploader_name }}</span>
                <button
                  @click.stop="deleteOrphanSupplement(sup)"
                  :disabled="deletingOrphanId === sup.id"
                  class="ml-auto flex items-center justify-center w-5 h-5 rounded hover:bg-red-50 text-gray-300 hover:text-red-400 disabled:opacity-50 transition-colors"
                  title="移出待退貨管理（保留費用資料）"
                >
                  <Loader2 v-if="deletingOrphanId === sup.id" :size="11" class="animate-spin" />
                  <Trash2 v-else :size="11" />
                </button>
              </div>

              <!-- 建議配對 -->
              <div v-if="sup.suggested_match"
                class="mb-1.5 px-2 py-1 bg-amber-50 border border-amber-200 rounded-lg">
                <span class="text-[9px] text-amber-600 font-medium">✨ 建議配對至 {{ sup.suggested_match.serial_number }}</span>
              </div>

              <!-- 發票資訊 -->
              <div class="flex flex-wrap gap-x-3 gap-y-0.5 mb-1.5">
                <span v-if="sup.total_amount != null" class="text-[11px] font-medium text-gray-700">
                  NT${{ Number(sup.total_amount).toLocaleString() }}
                </span>
                <span v-if="sup.expense_date" class="text-[10px] text-gray-400">{{ sup.expense_date }}</span>
                <span v-if="sup.invoice_number" class="text-[10px] font-mono text-gray-400 truncate">{{ sup.invoice_number }}</span>
              </div>

              <!-- 備註 -->
              <div class="mb-1.5">
                <p class="text-[10px] rounded px-1.5 py-1"
                  :class="sup.user_description ? 'bg-amber-50 text-amber-700' : 'text-gray-300 italic'"
                  :title="sup.user_description || ''">
                  {{ sup.user_description || '無備註' }}
                </p>
              </div>

              <!-- 圖片縮圖 -->
              <div class="flex flex-wrap gap-1.5">
                <div v-for="(url, i) in (sup.item_image_url ?? [])" :key="'item-'+i"
                  class="relative cursor-zoom-in w-10 h-10 rounded-lg border border-gray-200 overflow-hidden flex items-center justify-center bg-gray-50"
                  @click.stop="isViewableImage(url) ? openLightbox(imgUrl(url)) : null">
                  <img v-if="isViewableImage(url)" :src="imgUrl(url)" alt="物品照"
                    class="w-full h-full object-cover hover:opacity-80 transition-opacity" />
                  <a v-else :href="imgUrl(url)" target="_blank" class="text-red-500 text-[9px] font-bold" @click.stop>PDF</a>
                  <span class="absolute bottom-0 inset-x-0 text-[7px] text-white bg-gray-600 text-center rounded-b-lg">品</span>
                </div>
                <div v-for="(url, i) in (sup.image_url ?? [])" :key="'exp-'+i"
                  class="relative cursor-zoom-in w-10 h-10 rounded-lg border border-gray-200 overflow-hidden flex items-center justify-center bg-gray-50"
                  @click.stop="isViewableImage(url) ? openLightbox(imgUrl(url)) : null">
                  <img v-if="isViewableImage(url)" :src="imgUrl(url)" alt="憑證"
                    class="w-full h-full object-cover hover:opacity-80 transition-opacity" />
                  <a v-else :href="imgUrl(url)" target="_blank" class="text-red-500 text-[9px] font-bold" @click.stop>PDF</a>
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

  <!-- 補件類型下拉（fixed 定位，z 層級高於 modal 及確認對話框） -->
  <Teleport to="body">
    <div
      v-if="relationTypeDropdownId && dropdownExpense"
      class="fixed inset-0 z-[65]"
      @click="relationTypeDropdownId = null; dropdownExpense = null"
    />
    <div
      v-if="relationTypeDropdownId && dropdownExpense"
      class="fixed z-[66] bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden"
      :style="{ top: dropdownPos.top + 'px', left: dropdownPos.left + 'px', minWidth: '92px' }"
      @click.stop
    >
      <button
        v-for="opt in RELATION_TYPE_OPTIONS"
        :key="opt.value"
        @click="changeRelationType(dropdownExpense, opt.value)"
        class="w-full text-left text-[11px] px-2.5 py-1.5 transition-colors flex items-center gap-1.5"
        :class="[opt.optionClass, (dropdownExpense.relation_type === opt.value || (dropdownExpense.relation_type === 'SUPPLEMENT' && opt.value === 'RETURN_SUPPLEMENT')) ? 'font-semibold' : 'text-gray-600']"
      >
        <span
          class="w-1.5 h-1.5 rounded-full inline-block shrink-0"
          :class="(dropdownExpense.relation_type === opt.value || (dropdownExpense.relation_type === 'SUPPLEMENT' && opt.value === 'RETURN_SUPPLEMENT')) ? 'bg-current' : 'border border-gray-300'"
        />
        {{ opt.label }}
      </button>
    </div>
  </Teleport>

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
        :src="lightboxUrl" alt="圖片預覽"
        class="max-w-full max-h-full object-contain rounded-lg shadow-2xl cursor-default"
        @click.stop
      />
      <button @click="closeLightbox" class="absolute top-4 right-4 text-white/60 hover:text-white transition-colors">
        <X :size="28" />
      </button>
    </div>
  </Teleport>
</template>
