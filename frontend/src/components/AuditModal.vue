<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useExpenseStore } from '../stores/expenseStore'
import { fetchExpenseImages, updateExpenseImage } from '../api/expenseApi'
import { getRosterList } from '../api/rosterApi'
import { fetchDepartments, fetchExpenseCategories, fetchVoucherCategories } from '../api/configApi'
import { toast } from 'vue3-toastify'
import {
  ImagePlus,
  CheckCircle2,
  Save,
  X,
  CalendarDays,
  ZoomIn,
  Loader2,
  RefreshCw,
  ScanLine,
} from 'lucide-vue-next'
import { API_BASE_URL } from '../utils/axios'

const store = useExpenseStore()

// 後端 Base URL（供子圖片拼接完整路徑）
const BACKEND_BASE_URL = API_BASE_URL

// 憑證類別代碼對應中文名稱（動態載入，預設值供 fallback）
const voucherCategoryOptions = ref([
  { value: 'INVOICE', label: '發票' },
  { value: 'RECEIPT', label: '收據' },
  { value: 'LABOR_FORM', label: '勞報單' },
  { value: 'DEPOSIT', label: '押金' },
  { value: 'RETURN', label: '退貨' },
  { value: 'OTHER', label: '其他' },
])

// 費用父子科目（動態載入）
const expenseCategoryParents = ref([])

// ── 圖片分類編輯狀態（必須在依賴它的 computed 之前宣告）──────────
const editingImageId = ref(null)
const editImageForm = ref({})
const isSavingImageClass = ref(false)
let _suppressParentWatch = false

// 根據父科目 key 取得子科目清單
const expenseCategoryChildren = computed(() => {
  const parentKey = editImageForm.value.expense_parent_category
  if (!parentKey) return []
  const parent = expenseCategoryParents.value.find(p => p.key === parentKey)
  return parent?.children ?? []
})

// 父科目下拉選項
const expenseParentOptions = computed(() =>
  expenseCategoryParents.value.map(p => ({ value: p.key, label: p.label }))
)

// 憑證類別 key → label 查找（供 View mode badge 顯示）
const voucherCategoryLabel = computed(() => {
  const map = {}
  voucherCategoryOptions.value.forEach(o => { map[o.value] = o.label })
  return map
})

// 父科目 key → label 查找（供 View mode badge 顯示）
const parentCategoryLabel = computed(() => {
  const map = {}
  expenseCategoryParents.value.forEach(p => { map[p.key] = p.label })
  return map
})

function startEditImage(img) {
  _suppressParentWatch = true
  editingImageId.value = img.id
  editImageForm.value = {
    is_voucher: img.is_voucher,
    voucher_category: img.voucher_category ?? '',
    expense_parent_category: img.expense_parent_category ?? '',
    expense_category: img.expense_category ?? '',
  }
  nextTick(() => { _suppressParentWatch = false })
}

// 父科目切換時清空子科目（startEditImage 呼叫期間暫停，避免誤清 OCR 已填的值）
watch(
  () => editImageForm.value.expense_parent_category,
  () => {
    if (_suppressParentWatch) return
    editImageForm.value.expense_category = ''
  }
)

function cancelEditImage() {
  editingImageId.value = null
}

async function saveImageClassification(img) {
  isSavingImageClass.value = true
  try {
    const payload = { ...editImageForm.value }
    const oldIsVoucher = img.is_voucher
    for (const k of ['voucher_category', 'expense_parent_category', 'expense_category']) {
      if (payload[k] === '') payload[k] = null
    }
    await updateExpenseImage(form.value.id, img.id, payload)

    // 更新子圖片本地狀態
    const idx = subImages.value.findIndex(i => i.id === img.id)
    if (idx !== -1) subImages.value[idx] = { ...subImages.value[idx], ...payload }

    // 若 is_voucher 改變，同步更新費用影像 / 物品影像輪播陣列
    const newIsVoucher = payload.is_voucher ?? oldIsVoucher
    if (newIsVoucher !== oldIsVoucher) {
      const fullUrl = img.image_url.startsWith('http')
        ? img.image_url
        : `${BACKEND_BASE_URL}/${img.image_url}`
      if (oldIsVoucher) {
        form.value.image_url = (form.value.image_url || []).filter(u => u !== fullUrl)
        form.value.item_image_url = [...(form.value.item_image_url || []), fullUrl]
      } else {
        form.value.item_image_url = (form.value.item_image_url || []).filter(u => u !== fullUrl)
        form.value.image_url = [...(form.value.image_url || []), fullUrl]
      }
      activeExpenseIdx.value = Math.min(activeExpenseIdx.value, Math.max(0, (form.value.image_url || []).length - 1))
      activeItemIdx.value = Math.min(activeItemIdx.value, Math.max(0, (form.value.item_image_url || []).length - 1))
    }

    // 從子圖片重新計算左側憑證類別顯示
    form.value.voucher_categories = subImages.value
      .filter(i => i.is_voucher && i.voucher_category)
      .map(i => voucherCategoryLabel.value[i.voucher_category] ?? i.voucher_category)

    editingImageId.value = null
    toast.success('分類已更新')
  } catch {
    toast.error('更新失敗，請稍後再試')
  } finally {
    isSavingImageClass.value = false
  }
}

// ── 本地表單（從 store.selectedExpense 複製，避免直接污染 store）──
const form = ref({})

// Create Mode：store.selectedExpense 存在但沒有 id 時為新增模式
const isCreateMode = computed(() => !form.value.id)

// 防止重複送出
const isSubmitting = ref(false)
const submitError = ref('')

// 重新辨識進行中
const isReOcring = ref(false)

// 圖片上傳 refs（append）
const expenseFileInput = ref(null)
const itemFileInput = ref(null)
// 圖片替換 refs（replace at index）
const replaceExpenseFileInput = ref(null)
const replaceItemFileInput = ref(null)

// 上傳中狀態
const isUploadingExpenseImg = ref(false)
const isUploadingItemImg = ref(false)
const isReplacingExpenseImg = ref(false)
const isReplacingItemImg = ref(false)

// 輪播目前顯示的索引
const activeExpenseIdx = ref(0)
const activeItemIdx = ref(0)

// Create Mode 本地暫存（{ file: File, previewUrl: string }）
const pendingExpenseImages = ref([])
const pendingItemImages = ref([])

// 合併「已上傳遠端 URL」與「本地預覽 URL」供輪播使用
const allExpenseImages = computed(() => [
  ...(form.value.image_url || []),
  ...pendingExpenseImages.value.map(p => p.previewUrl),
])
const allItemImages = computed(() => [
  ...(form.value.item_image_url || []),
  ...pendingItemImages.value.map(p => p.previewUrl),
])

watch(
  () => store.selectedExpense,
  (expense) => {
    if (expense) {
      form.value = { ...expense }
      activeExpenseIdx.value = 0
      activeItemIdx.value = 0
      // 切換費用時清空暫存
      pendingExpenseImages.value.forEach(p => URL.revokeObjectURL(p.previewUrl))
      pendingItemImages.value.forEach(p => URL.revokeObjectURL(p.previewUrl))
      pendingExpenseImages.value = []
      pendingItemImages.value = []
      // 載入子圖片清單（Edit Mode 才有 id）
      subImages.value = []
      if (expense.id) {
        loadSubImages(expense.id)
      }
    }
  },
  { immediate: true }
)

// ── 員工名冊（費用提報者下拉來源）────────────────────────────────
const rosterEmployees = ref([])

async function loadRosterEmployees() {
  try {
    const res = await getRosterList({ page: 0, size: 1000 })
    rosterEmployees.value = res.data?.data?.content ?? []
  } catch {
    rosterEmployees.value = []
  }
}

// ── 選項清單 ────────────────────────────────────────────────────
const deptOptions = ref([])

onMounted(async () => {
  if (localStorage.getItem('acctassist_token')) loadRosterEmployees()
  try {
    const [deptRes, catRes, vcRes] = await Promise.all([
      fetchDepartments(),
      fetchExpenseCategories(),
      fetchVoucherCategories(),
    ])
    deptOptions.value = deptRes.data?.data?.departments ?? []
    expenseCategoryParents.value = catRes.data?.data?.parents ?? []
    if (vcRes.data?.data?.voucher_categories?.length) {
      voucherCategoryOptions.value = vcRes.data.data.voucher_categories.map(c => ({
        value: c.key,
        label: c.label,
      }))
    }
  } catch {
    // fallback：使用預設值
  }
})

// 選擇費用提報者後自動帶入其組別
watch(
  () => form.value.submitter_name,
  (name) => {
    if (!name) return
    const employee = rosterEmployees.value.find(e => e.name === name)
    if (employee) {
      form.value.submitter_dept = employee.department
    }
  }
)
const certificateTypes = ['發票', '收據', '勞報', '押金', '退貨', '車票', '其他']

// ── 退回單據對話框 ───────────────────────────────────────────────
const showRejectDialog = ref(false)

async function handleReject() {
  if (isSubmitting.value) return
  isSubmitting.value = true
  try {
    await store.rejectExpense(form.value.id)
    showRejectDialog.value = false
  } finally {
    isSubmitting.value = false
  }
}

// ── 圖片放大燈箱 ─────────────────────────────────────────────────
const lightboxOpen = ref(false)
const lightboxSrc = ref('')

function openLightbox(src) {
  lightboxSrc.value = src
  lightboxOpen.value = true
}

// ── 事件處理 ─────────────────────────────────────────────────────
function handleClose() {
  if (isSubmitting.value) return  // 送出中禁止關閉
  store.closeAudit()
}

// 點擊遮罩關閉
function handleOverlayClick(e) {
  if (e.target === e.currentTarget) handleClose()
}

async function handleSave() {
  if (isSubmitting.value) return
  submitError.value = ''
  isSubmitting.value = true
  try {
    if (isCreateMode.value) {
      // 1. 建立費用，拿回含 UUID 的新物件
      const created = await store.createExpense(form.value)
      // 2. 將本地暫存圖片逐一上傳（依選取順序）
      if (created?.id) {
        const pendingUploads = [
          ...pendingExpenseImages.value.map(p => ({ file: p.file, type: 'expense' })),
          ...pendingItemImages.value.map(p => ({ file: p.file, type: 'item' })),
        ]
        for (const { file, type } of pendingUploads) {
          await store.uploadImage(created.id, file, type)
        }
      }
      // 3. 清空暫存並關閉
      pendingExpenseImages.value.forEach(p => URL.revokeObjectURL(p.previewUrl))
      pendingItemImages.value.forEach(p => URL.revokeObjectURL(p.previewUrl))
      pendingExpenseImages.value = []
      pendingItemImages.value = []
      store.closeAudit()
      toast.success('儲存成功！')
    } else {
      await store.saveExpense(form.value.id, form.value, false)
      toast.success('儲存成功！')
    }
  } catch {
    const msg = isCreateMode.value ? '新增失敗，請稍後再試' : '儲存失敗，請稍後再試'
    submitError.value = msg
    toast.error(msg)
  } finally {
    isSubmitting.value = false
  }
}

async function handleApprove() {
  if (isSubmitting.value || isCreateMode.value) return
  submitError.value = ''
  isSubmitting.value = true
  try {
    await store.saveExpense(form.value.id, form.value, true)
    toast.success('儲存成功！')
  } catch {
    submitError.value = '審核失敗，請稍後再試'
    toast.error('審核失敗，請稍後再試')
  } finally {
    isSubmitting.value = false
  }
}

// 輪播目前顯示的圖片 URL（合併遠端 + 本地預覽）
const currentExpenseImage = computed(() => allExpenseImages.value[activeExpenseIdx.value] ?? null)
const currentItemImage = computed(() => allItemImages.value[activeItemIdx.value] ?? null)

// ── 圖片追加（底部「新增」按鈕觸發）─────────────────────────────
async function handleAppendImage(event, imageType) {
  const file = event.target.files?.[0]
  if (!file) return
  const isExpense = imageType === 'expense'

  if (isCreateMode.value) {
    // Create Mode：本地暫存，不呼叫 API
    const previewUrl = URL.createObjectURL(file)
    if (isExpense) {
      pendingExpenseImages.value.push({ file, previewUrl })
      activeExpenseIdx.value = allExpenseImages.value.length - 1
    } else {
      pendingItemImages.value.push({ file, previewUrl })
      activeItemIdx.value = allItemImages.value.length - 1
    }
    event.target.value = ''
    return
  }

  // Edit Mode：直接上傳 API
  if (isExpense) isUploadingExpenseImg.value = true
  else isUploadingItemImg.value = true
  try {
    const newUrls = await store.uploadImage(form.value.id, file, imageType)
    if (isExpense) {
      form.value.image_url = newUrls
      activeExpenseIdx.value = newUrls.length - 1
    } else {
      form.value.item_image_url = newUrls
      activeItemIdx.value = newUrls.length - 1
    }
    toast.success('圖片上傳成功！')
  } catch {
    toast.error('圖片上傳失敗，請確認檔案格式是否為圖片')
  } finally {
    if (isExpense) isUploadingExpenseImg.value = false
    else isUploadingItemImg.value = false
    event.target.value = ''
  }
}

// ── 圖片替換（大圖右上角「更換」按鈕觸發）───────────────────────
async function handleReplaceImage(event, imageType, idx) {
  const file = event.target.files?.[0]
  if (!file || isCreateMode.value) return
  const isExpense = imageType === 'expense'
  if (isExpense) isReplacingExpenseImg.value = true
  else isReplacingItemImg.value = true
  try {
    const newUrls = await store.replaceImage(form.value.id, file, imageType, idx)
    if (isExpense) form.value.image_url = newUrls
    else form.value.item_image_url = newUrls
    toast.success('圖片上傳成功！')
  } catch {
    toast.error('圖片替換失敗，請確認檔案格式是否為圖片')
  } finally {
    if (isExpense) isReplacingExpenseImg.value = false
    else isReplacingItemImg.value = false
    event.target.value = ''
  }
}

// ── 子圖片清單（T6 API: GET /api/v1/expenses/{id}/images）────────
const subImages = ref([])
const isLoadingSubImages = ref(false)

async function loadSubImages(expenseId) {
  if (!expenseId) {
    subImages.value = []
    return
  }
  isLoadingSubImages.value = true
  try {
    const res = await fetchExpenseImages(expenseId)
    subImages.value = res.data?.data?.images ?? []
  } catch (err) {
    console.error('[AuditModal] 載入子圖片失敗：', err)
    subImages.value = []
  } finally {
    isLoadingSubImages.value = false
  }
}

// 從 OCR JSON 字串中安全解析 total_amount
function parseOcrAmount(ocrResult) {
  if (!ocrResult) return null
  try {
    const parsed = typeof ocrResult === 'string' ? JSON.parse(ocrResult) : ocrResult
    return parsed?.total_amount ?? null
  } catch {
    return null
  }
}

// 從 OCR JSON 字串中解析所有可顯示的細項欄位
function parseOcrFields(ocrResult) {
  if (!ocrResult) return null
  try {
    const p = typeof ocrResult === 'string' ? JSON.parse(ocrResult) : ocrResult
    return {
      expense_date: p?.expense_date ?? null,
      invoice_number: p?.invoice_number ?? null,
      seller_name: p?.seller_name ?? null,
      item_description: p?.item_description ?? null,
      route: p?.route_from && p?.route_to
        ? `${p.route_from} → ${p.route_to}`
        : (p?.route_from || p?.route_to || null),
      overall_confidence: p?.overall_confidence != null
        ? Math.round(p.overall_confidence * 100)
        : null,
    }
  } catch {
    return null
  }
}

// ── 重新辨識 ─────────────────────────────────────────────────────
async function handleReOcr() {
  if (isReOcring.value || isSubmitting.value || isCreateMode.value) return
  isReOcring.value = true
  try {
    const updated = await store.reOcrExpense(form.value.id)
    // 只填回有值的欄位，不覆蓋 OCR 未辨識到的欄位
    if (updated.expense_date)         form.value.expense_date     = updated.expense_date
    if (updated.invoice_number)       form.value.invoice_number   = updated.invoice_number
    if (updated.total_amount != null) form.value.total_amount     = updated.total_amount
    if (updated.net_amount != null)   form.value.net_amount       = updated.net_amount
    if (updated.tax_amount != null)   form.value.tax_amount       = updated.tax_amount
    if (updated.seller_tax_id)        form.value.seller_tax_id    = updated.seller_tax_id
    if (updated.seller_name)          form.value.seller_name      = updated.seller_name
    if (updated.item_description)     form.value.item_description = updated.item_description
    toast.success('重新辨識完成，欄位已更新！')
  } catch (err) {
    // 完整 log 供除錯：HTTP status、後端 detail、JS error 類型
    console.error('[ReOCR] 重新辨識失敗', {
      status: err?.response?.status,
      detail: err?.response?.data?.detail,
      code: err?.code,
      message: err?.message,
    })
    // 區分 timeout（ECONNABORTED）與其他錯誤（422 OCR 失敗、500 伺服器錯誤）
    const isTimeout = err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')
    const detail = err?.response?.data?.detail
    if (isTimeout) {
      toast.error('辨識逾時，請稍後再試（OCR 處理時間過長）')
    } else if (detail) {
      toast.error(`重新辨識失敗：${detail}`)
    } else if (!err?.response) {
      toast.error('無法連線到後端，請確認服務是否啟動')
    } else {
      toast.error(`重新辨識失敗（HTTP ${err?.response?.status}），請確認圖片是否正常`)
    }
  } finally {
    isReOcring.value = false
  }
}

// 金額格式化（顯示用）
function formatAmount(val) {
  if (val === null || val === undefined || val === '') return ''
  return Number(val).toLocaleString()
}

// 日期時間格式化：ISO 字串 → YYYY-MM-DD HH:mm
function formatDateTime(val) {
  if (!val) return '-'
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`
}
</script>

<template>
  <Teleport to="body">
    <!-- 全螢幕遮罩 -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="store.isAuditModalOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        @click="handleOverlayClick"
      >
        <!-- Modal 本體 -->
        <Transition
          enter-active-class="transition duration-200 ease-out"
          enter-from-class="opacity-0 scale-95"
          enter-to-class="opacity-100 scale-100"
          leave-active-class="transition duration-150 ease-in"
          leave-from-class="opacity-100 scale-100"
          leave-to-class="opacity-0 scale-95"
        >
          <div
            v-if="store.isAuditModalOpen"
            class="relative flex flex-col bg-white rounded-lg shadow-2xl w-full max-w-6xl"
            style="height: 92vh"
            @click.stop
          >

            <!-- ══════════════════════════════════════════════
                 主體：左側表單 + 右側影像
                 ══════════════════════════════════════════════ -->
            <div class="flex flex-1 overflow-hidden">

              <!-- ────────────────────────────────────────────
                   左側表單區（可捲動）
                   ──────────────────────────────────────────── -->
              <div class="w-80 shrink-0 overflow-y-auto border-r border-gray-200 p-5 space-y-4">

                <!-- ▌ Modal 標題 ▌ -->
                <h2 class="text-base font-semibold text-gray-800">
                  {{ isCreateMode ? '新增費用' : '審核編輯' }}
                </h2>

                <!-- ▌唯讀區塊（Edit Mode）/ 可編輯（Create Mode）▌ -->
                <!-- 案件編號（Edit Mode 唯讀） -->
                <div v-if="!isCreateMode" class="space-y-1">
                  <label class="block text-sm text-gray-600">案件編號：</label>
                  <div class="flex items-center gap-2">
                    <div class="bg-blue-50 border border-blue-200 rounded px-3 py-2 text-sm font-mono font-medium text-blue-700 flex-1">
                      {{ form.serial_number || '-' }}
                    </div>
                    <!-- Sprint 3：觸發來源 Badge -->
                    <span
                      v-if="form.trigger_by === 'auto_split'"
                      class="flex-shrink-0 text-xs px-2 py-1 rounded bg-yellow-100 text-yellow-700 border border-yellow-200"
                      title="系統於 60 秒無操作後自動送出"
                    >⏱ 自動送出</span>
                    <span
                      v-else-if="form.trigger_by === 'manual_button'"
                      class="flex-shrink-0 text-xs px-2 py-1 rounded bg-green-100 text-green-700 border border-green-200"
                      title="使用者手動按確認送出"
                    >✅ 手動送出</span>
                  </div>
                </div>

                <!-- 上傳日期 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">上傳日期：</label>
                  <template v-if="isCreateMode">
                    <input
                      v-model="form.upload_date"
                      type="text"
                      placeholder="YYYY-MM-DD"
                      class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </template>
                  <template v-else>
                    <div class="flex items-center gap-2 bg-gray-100 border border-gray-200 rounded px-3 py-2 text-sm text-gray-600">
                      <span class="flex-1">{{ formatDateTime(form.upload_date) }}</span>
                      <CalendarDays :size="15" class="text-gray-400" />
                    </div>
                  </template>
                </div>

                <!-- 上傳者 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">上傳者：</label>
                  <template v-if="isCreateMode">
                    <input
                      v-model="form.uploader_name"
                      type="text"
                      placeholder="上傳者姓名"
                      class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </template>
                  <template v-else>
                    <div class="bg-gray-100 border border-gray-200 rounded px-3 py-2 text-sm text-gray-600">
                      {{ form.uploader_name || '-' }}
                    </div>
                  </template>
                </div>

                <!-- 上傳者組別 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">上傳者組別：</label>
                  <template v-if="isCreateMode">
                    <select
                      v-model="form.uploader_dept"
                      class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                    >
                      <option value="">-- 請選擇 --</option>
                      <option v-for="dept in deptOptions" :key="dept" :value="dept">{{ dept }}</option>
                    </select>
                  </template>
                  <template v-else>
                    <div class="bg-gray-100 border border-gray-200 rounded px-3 py-2 text-sm text-gray-600">
                      {{ form.uploader_dept || '-' }}
                    </div>
                  </template>
                </div>

                <!-- 分隔線 -->
                <hr class="border-gray-200" />

                <!-- ▌可編輯區塊 ▌ -->

                <!-- 費用提報者 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">費用提報者：</label>
                  <select
                    v-model="form.submitter_name"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                  >
                    <option value="">-- 請選擇 --</option>
                    <option v-for="emp in rosterEmployees" :key="emp.id" :value="emp.name">{{ emp.name }}</option>
                  </select>
                </div>

                <!-- 費用提報者組別 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">費用提報者組別：</label>
                  <select
                    v-model="form.submitter_dept"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                  >
                    <option value="">-- 請選擇 --</option>
                    <option v-for="dept in deptOptions" :key="dept" :value="dept">{{ dept }}</option>
                  </select>
                </div>

                <!-- 費用日期（必填）-->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">
                    費用日期：<span class="text-red-500">*</span>
                  </label>
                  <input
                    v-model="form.expense_date"
                    type="date"
                    required
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>

                <!-- 發票號碼 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">發票號碼：</label>
                  <input
                    v-model="form.invoice_number"
                    type="text"
                    placeholder="例：AB-12345678"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>

                <!-- 含稅金額 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">含稅金額：</label>
                  <input
                    v-model.number="form.total_amount"
                    type="number"
                    min="0"
                    placeholder="0"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>

                <!-- 未稅金額 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">未稅金額：</label>
                  <input
                    v-model.number="form.net_amount"
                    type="number"
                    min="0"
                    placeholder="0"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>

                <!-- 營業稅額 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">營業稅額：</label>
                  <input
                    v-model.number="form.tax_amount"
                    type="number"
                    min="0"
                    placeholder="0"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>

                <!-- 賣方統編 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">賣方統編：</label>
                  <input
                    v-model="form.seller_tax_id"
                    type="text"
                    placeholder="8 位數統一編號"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>

                <!-- 賣方公司 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">賣方公司：</label>
                  <input
                    v-model="form.seller_name"
                    type="text"
                    placeholder="公司名稱"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>

                <!-- 項目說明 -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">項目說明：</label>
                  <textarea
                    v-model="form.item_description"
                    rows="3"
                    placeholder="請輸入費用說明..."
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"
                  ></textarea>
                </div>

                <!-- 憑證類別（唯讀：優先顯示 voucher_categories 中文清單） -->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">憑證類別：</label>
                  <div class="bg-gray-100 border border-gray-200 rounded px-3 py-2 text-sm text-gray-600 min-h-[38px]">
                    <template v-if="form.voucher_categories && form.voucher_categories.length > 0">
                      {{ form.voucher_categories.map(c => voucherCategoryLabel[c] ?? c).join('、') }}
                    </template>
                    <template v-else>
                      {{ form.certificate_type || '-' }}
                    </template>
                  </div>
                </div>

                <!-- 備註（user_description，唯讀，null 時不顯示） -->
                <div v-if="form.user_description" class="space-y-1">
                  <label class="block text-sm text-gray-600">備註：</label>
                  <div class="bg-gray-100 border border-gray-200 rounded px-3 py-2 text-sm text-gray-600 whitespace-pre-wrap">
                    {{ form.user_description }}
                  </div>
                </div>

                <!-- 關聯鏈資訊（有 relation_type 或 void_reason 時顯示） -->
                <div
                  v-if="form.relation_type || form.void_reason || !form.is_active"
                  class="space-y-1 rounded border px-3 py-2"
                  :class="form.is_active === false ? 'bg-gray-50 border-gray-300' : 'bg-amber-50 border-amber-200'"
                >
                  <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">關聯鏈資訊</label>
                  <div v-if="!form.is_active" class="flex items-center gap-2 text-sm text-gray-500">
                    <span class="px-1.5 py-0.5 rounded bg-gray-200 text-gray-600 text-xs">已作廢</span>
                    <span v-if="form.void_reason">{{ form.void_reason }}</span>
                  </div>
                  <div v-if="form.relation_type" class="text-sm text-amber-800">
                    <span class="font-medium">類型：</span>
                    <span>{{
                      form.relation_type === 'VOID_REPLACE' ? '換單（取代原始報帳）' :
                      form.relation_type === 'CREDIT_NOTE'  ? '折讓單（原始報帳已調整淨額）' :
                      form.relation_type === 'SUPPLEMENT'   ? '差額補足（連結至原始報帳）' :
                      form.relation_type
                    }}</span>
                  </div>
                  <div v-if="form.referenced_invoice_number" class="text-sm text-amber-800">
                    <span class="font-medium">參考發票：</span>
                    <span class="font-mono">{{ form.referenced_invoice_number }}</span>
                  </div>
                  <div v-if="form.parent_id" class="text-sm text-amber-800">
                    <span class="font-medium">原單 ID：</span>
                    <span class="font-mono text-xs">{{ form.parent_id }}</span>
                  </div>
                </div>

                <!-- 財產（必填）-->
                <div class="space-y-1">
                  <label class="block text-sm text-gray-600">
                    財產：<span class="text-red-500">*</span>
                  </label>
                  <select
                    v-model="form.is_asset"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                  >
                    <option :value="false">否</option>
                    <option :value="true">是</option>
                  </select>
                </div>

                <!-- 退貨之原始資料 -->
                <div class="space-y-1 pb-4">
                  <label class="block text-sm text-gray-600">退貨之原始資料：</label>
                  <textarea
                    v-model="form.return_original_data"
                    rows="3"
                    placeholder="請輸入原發票之號碼、或原收據之日期與金額"
                    class="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"
                  ></textarea>
                </div>

              </div>
              <!-- /左側表單 -->

              <!-- ────────────────────────────────────────────
                   右側影像區（可捲動）
                   ──────────────────────────────────────────── -->
              <div class="flex-1 overflow-y-auto p-5 space-y-6 bg-gray-50">

                <!-- ── 費用影像 ───────────────────────────────── -->
                <div>
                  <h3 class="text-sm font-semibold text-gray-700 mb-3">費用影像</h3>

                  <!-- 隱藏 file inputs -->
                  <input ref="replaceExpenseFileInput" type="file" accept="image/*" class="hidden"
                    @change="(e) => handleReplaceImage(e, 'expense', activeExpenseIdx)" />
                  <input ref="expenseFileInput" type="file" accept="image/*" class="hidden"
                    @change="(e) => handleAppendImage(e, 'expense')" />

                  <!-- 有圖（含本地暫存）：輪播大圖 + 更換按鈕 + 縮圖列 -->
                  <div v-if="allExpenseImages.length > 0">
                    <div class="relative group mb-2">
                      <img
                        :src="currentExpenseImage"
                        alt="費用影像"
                        class="w-full rounded-lg border border-gray-300 object-contain cursor-zoom-in"
                        style="max-height: 400px"
                        @click="openLightbox(currentExpenseImage)"
                      />
                      <!-- 右上角：更換按鈕（Edit Mode 且為已上傳的圖才顯示） -->
                      <button
                        v-if="!isCreateMode && activeExpenseIdx < (form.image_url || []).length"
                        @click="replaceExpenseFileInput?.click()"
                        class="absolute top-2 right-2 flex items-center gap-1 bg-black/60 hover:bg-black/80 text-white rounded px-2 py-1 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                        title="替換此張圖片"
                      >
                        <Loader2 v-if="isReplacingExpenseImg" :size="11" class="animate-spin" />
                        <RefreshCw v-else :size="11" />
                        更換
                      </button>
                      <!-- 左上角：放大按鈕 -->
                      <button
                        @click="openLightbox(currentExpenseImage)"
                        class="absolute top-2 left-2 bg-black/50 hover:bg-black/70 text-white rounded p-1.5 opacity-0 group-hover:opacity-100 transition-opacity"
                        title="放大檢視"
                      >
                        <ZoomIn :size="16" />
                      </button>
                    </div>
                    <!-- 縮圖列（多於 1 張才顯示） -->
                    <div v-if="allExpenseImages.length > 1" class="flex gap-2 flex-wrap">
                      <div
                        v-for="(url, i) in allExpenseImages"
                        :key="i"
                        class="w-14 h-14 rounded border-2 cursor-pointer overflow-hidden transition-colors"
                        :class="i === activeExpenseIdx
                          ? 'border-blue-500'
                          : 'border-gray-200 hover:border-gray-400'"
                        @click="activeExpenseIdx = i"
                      >
                        <img :src="url" class="w-full h-full object-cover" />
                      </div>
                    </div>
                  </div>

                  <!-- 無圖 Placeholder -->
                  <div
                    v-else
                    class="w-full rounded-lg border-2 border-dashed border-blue-200 bg-blue-50 flex flex-col items-center justify-center text-gray-400 cursor-default"
                    style="min-height: 280px"
                  >
                    <ImagePlus :size="40" class="mb-3 text-blue-200" />
                    <p class="text-sm">尚無費用影像</p>
                    <p class="text-xs text-gray-400 mt-1">點擊底部「新增費用影像」上傳 · 支援 JPG、PNG、WEBP</p>
                  </div>
                </div>

                <!-- ── 物品影像 ───────────────────────────────── -->
                <div class="pb-2">
                  <h3 class="text-sm font-semibold text-gray-700 mb-3">物品影像</h3>

                  <!-- 隱藏 file inputs -->
                  <input ref="replaceItemFileInput" type="file" accept="image/*" class="hidden"
                    @change="(e) => handleReplaceImage(e, 'item', activeItemIdx)" />
                  <input ref="itemFileInput" type="file" accept="image/*" class="hidden"
                    @change="(e) => handleAppendImage(e, 'item')" />

                  <!-- 有圖（含本地暫存）：輪播大圖 + 更換按鈕 + 縮圖列 -->
                  <div v-if="allItemImages.length > 0">
                    <div class="relative group mb-2">
                      <img
                        :src="currentItemImage"
                        alt="物品影像"
                        class="w-full rounded-lg border border-gray-300 object-contain cursor-zoom-in"
                        style="max-height: 400px"
                        @click="openLightbox(currentItemImage)"
                      />
                      <!-- 右上角：更換按鈕（Edit Mode 且為已上傳的圖才顯示） -->
                      <button
                        v-if="!isCreateMode && activeItemIdx < (form.item_image_url || []).length"
                        @click="replaceItemFileInput?.click()"
                        class="absolute top-2 right-2 flex items-center gap-1 bg-black/60 hover:bg-black/80 text-white rounded px-2 py-1 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                        title="替換此張圖片"
                      >
                        <Loader2 v-if="isReplacingItemImg" :size="11" class="animate-spin" />
                        <RefreshCw v-else :size="11" />
                        更換
                      </button>
                      <!-- 左上角：放大按鈕 -->
                      <button
                        @click="openLightbox(currentItemImage)"
                        class="absolute top-2 left-2 bg-black/50 hover:bg-black/70 text-white rounded p-1.5 opacity-0 group-hover:opacity-100 transition-opacity"
                        title="放大檢視"
                      >
                        <ZoomIn :size="16" />
                      </button>
                    </div>
                    <!-- 縮圖列（多於 1 張才顯示） -->
                    <div v-if="allItemImages.length > 1" class="flex gap-2 flex-wrap">
                      <div
                        v-for="(url, i) in allItemImages"
                        :key="i"
                        class="w-14 h-14 rounded border-2 cursor-pointer overflow-hidden transition-colors"
                        :class="i === activeItemIdx
                          ? 'border-blue-500'
                          : 'border-gray-200 hover:border-gray-400'"
                        @click="activeItemIdx = i"
                      >
                        <img :src="url" class="w-full h-full object-cover" />
                      </div>
                    </div>
                  </div>

                  <!-- 無圖 Placeholder -->
                  <div
                    v-else
                    class="w-full rounded-lg border-2 border-dashed border-blue-200 bg-blue-50 flex flex-col items-center justify-center text-gray-400 cursor-default"
                    style="min-height: 280px"
                  >
                    <ImagePlus :size="40" class="mb-3 text-blue-200" />
                    <p class="text-sm">尚無物品影像</p>
                    <p class="text-xs text-gray-400 mt-1">點擊底部「新增物品影像」上傳 · 支援 JPG、PNG、WEBP</p>
                  </div>
                </div>

                <!-- ── 子圖片清單（T6 API: 多張上傳的各憑證圖片）─────── -->
                <div v-if="!isCreateMode" class="pb-2">
                  <h3 class="text-sm font-semibold text-gray-700 mb-3">
                    憑證子圖片
                    <span v-if="form.image_count" class="ml-1 text-xs font-normal text-gray-400">
                      （共 {{ form.image_count }} 張）
                    </span>
                  </h3>

                  <!-- 載入中 -->
                  <div v-if="isLoadingSubImages" class="flex items-center justify-center py-8 text-gray-400">
                    <Loader2 :size="22" class="animate-spin mr-2" />
                    <span class="text-sm">載入中...</span>
                  </div>

                  <!-- 有子圖片 -->
                  <div v-else-if="subImages.length > 0" class="space-y-3">
                    <div
                      v-for="(img, i) in subImages"
                      :key="img.id || i"
                      class="flex items-start gap-3 bg-white border border-gray-200 rounded-lg p-3"
                    >
                      <!-- 縮圖 -->
                      <img
                        :src="BACKEND_BASE_URL + '/' + img.image_url"
                        :alt="'子圖片 ' + (i + 1)"
                        class="w-16 h-16 object-cover rounded border border-gray-200 cursor-zoom-in shrink-0"
                        @click="openLightbox(BACKEND_BASE_URL + '/' + img.image_url)"
                      />

                      <!-- View mode -->
                      <template v-if="editingImageId !== img.id">
                        <div class="flex-1 min-w-0 space-y-1">
                          <!-- is_voucher badge -->
                          <span
                            :class="img.is_voucher
                              ? 'bg-green-100 text-green-700'
                              : 'bg-gray-100 text-gray-500'"
                            class="inline-block text-xs font-medium px-2 py-0.5 rounded"
                          >
                            {{ img.is_voucher ? '憑證' : '非憑證' }}
                          </span>
                          <!-- voucher_category badge -->
                          <span
                            v-if="img.voucher_category"
                            class="ml-1 inline-block bg-blue-100 text-blue-700 text-xs font-medium px-2 py-0.5 rounded"
                          >
                            {{ voucherCategoryLabel[img.voucher_category] ?? img.voucher_category }}
                          </span>
                          <!-- expense parent + child badge -->
                          <span
                            v-if="img.expense_category || img.expense_parent_category"
                            class="ml-1 inline-block bg-purple-100 text-purple-700 text-xs font-medium px-2 py-0.5 rounded"
                          >
                            <template v-if="img.expense_parent_category && parentCategoryLabel[img.expense_parent_category]">
                              {{ parentCategoryLabel[img.expense_parent_category] }}
                              <template v-if="img.expense_category"> &gt; </template>
                            </template>
                            {{ img.expense_category }}
                          </span>
                          <!-- OCR 細項 -->
                          <template v-if="parseOcrFields(img.ocr_result)">
                            <div class="mt-1 space-y-0.5 text-xs text-gray-600">
                              <div v-if="parseOcrAmount(img.ocr_result) !== null">
                                金額：<span class="font-medium text-gray-800">NT$ {{ formatAmount(parseOcrAmount(img.ocr_result)) }}</span>
                              </div>
                              <div v-if="parseOcrFields(img.ocr_result).expense_date">
                                費用日期：<span class="font-medium text-gray-800">{{ parseOcrFields(img.ocr_result).expense_date }}</span>
                              </div>
                              <div v-if="parseOcrFields(img.ocr_result).invoice_number">
                                發票號碼：<span class="font-medium text-gray-800">{{ parseOcrFields(img.ocr_result).invoice_number }}</span>
                              </div>
                              <div v-if="parseOcrFields(img.ocr_result).seller_name">
                                賣方：<span class="font-medium text-gray-800">{{ parseOcrFields(img.ocr_result).seller_name }}</span>
                              </div>
                              <div v-if="parseOcrFields(img.ocr_result).route">
                                路線：<span class="font-medium text-gray-800">{{ parseOcrFields(img.ocr_result).route }}</span>
                              </div>
                              <div v-if="parseOcrFields(img.ocr_result).item_description">
                                品項：<span class="font-medium text-gray-800">{{ parseOcrFields(img.ocr_result).item_description }}</span>
                              </div>
                            </div>
                          </template>
                          <!-- 編輯按鈕 -->
                          <button
                            @click="startEditImage(img)"
                            class="mt-1 text-xs text-indigo-600 hover:text-indigo-800 underline"
                          >
                            編輯分類
                          </button>
                        </div>
                      </template>

                      <!-- Edit mode -->
                      <template v-else>
                        <div class="flex-1 min-w-0 space-y-2">
                          <!-- is_voucher -->
                          <label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                            <input type="checkbox" v-model="editImageForm.is_voucher" class="rounded" />
                            此張為憑證
                          </label>
                          <!-- voucher_category -->
                          <div>
                            <label class="block text-xs text-gray-500 mb-0.5">憑證類別</label>
                            <select
                              v-model="editImageForm.voucher_category"
                              :disabled="!editImageForm.is_voucher"
                              class="w-full text-xs border border-gray-300 rounded px-2 py-1 disabled:opacity-40"
                            >
                              <option value="">— 未設定 —</option>
                              <option v-for="opt in voucherCategoryOptions" :key="opt.value" :value="opt.value">
                                {{ opt.label }}
                              </option>
                            </select>
                          </div>
                          <!-- expense_parent_category -->
                          <div>
                            <label class="block text-xs text-gray-500 mb-0.5">費用科目（父）</label>
                            <select
                              v-model="editImageForm.expense_parent_category"
                              class="w-full text-xs border border-gray-300 rounded px-2 py-1"
                            >
                              <option value="">— 未設定 —</option>
                              <option v-for="opt in expenseParentOptions" :key="opt.value" :value="opt.value">
                                {{ opt.label }}
                              </option>
                            </select>
                          </div>
                          <!-- expense_category（子，根據父科目動態篩選） -->
                          <div>
                            <label class="block text-xs text-gray-500 mb-0.5">費用科目（子）</label>
                            <select
                              v-model="editImageForm.expense_category"
                              :disabled="!editImageForm.expense_parent_category"
                              class="w-full text-xs border border-gray-300 rounded px-2 py-1 disabled:opacity-40"
                            >
                              <option value="">— 未設定 —</option>
                              <option v-for="child in expenseCategoryChildren" :key="child.key" :value="child.label">
                                {{ child.label }}
                              </option>
                            </select>
                          </div>
                          <!-- 儲存 / 取消 -->
                          <div class="flex gap-2 pt-1">
                            <button
                              @click="saveImageClassification(img)"
                              :disabled="isSavingImageClass"
                              class="text-xs bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700 disabled:opacity-50"
                            >
                              {{ isSavingImageClass ? '儲存中...' : '儲存' }}
                            </button>
                            <button
                              @click="cancelEditImage"
                              class="text-xs border border-gray-300 text-gray-600 px-3 py-1 rounded hover:bg-gray-50"
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      </template>
                    </div>
                  </div>

                  <!-- 無子圖片 -->
                  <div v-else class="text-sm text-gray-400 py-4 text-center">—</div>
                </div>

              </div>
              <!-- /右側影像 -->

            </div>
            <!-- /主體 -->

            <!-- ══════════════════════════════════════════════
                 底部固定操作列（Sticky Footer）
                 ══════════════════════════════════════════════ -->
            <div class="shrink-0 border-t border-gray-200 bg-white px-5 py-3 flex items-center justify-between gap-2">
              <!-- 左側：錯誤提示 -->
              <span v-if="submitError" class="text-sm text-red-500">{{ submitError }}</span>
              <span v-else class="flex-1"></span>

              <!-- 右側：操作按鈕 -->
              <div class="flex items-center gap-2">
                <!-- 重新辨識（Edit Mode 且有費用影像才顯示） -->
                <button
                  v-if="!isCreateMode && (form.image_url || []).length > 0"
                  @click="handleReOcr"
                  :disabled="isReOcring || isSubmitting"
                  class="flex items-center gap-1.5 px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white text-sm rounded transition-colors"
                >
                  <Loader2 v-if="isReOcring" :size="15" class="animate-spin" />
                  <ScanLine v-else :size="15" />
                  {{ isReOcring ? '辨識中...' : '重新辨識' }}
                </button>

                <!-- 新增費用影像 -->
                <button
                  @click="expenseFileInput?.click()"
                  :disabled="isSubmitting || isUploadingExpenseImg"
                  class="flex items-center gap-1.5 px-4 py-2 bg-gray-500 hover:bg-gray-600 disabled:opacity-50 text-white text-sm rounded transition-colors"
                >
                  <Loader2 v-if="isUploadingExpenseImg" :size="15" class="animate-spin" />
                  <ImagePlus v-else :size="15" />
                  新增費用影像
                </button>

                <!-- 新增物品影像 -->
                <button
                  @click="itemFileInput?.click()"
                  :disabled="isSubmitting || isUploadingItemImg"
                  class="flex items-center gap-1.5 px-4 py-2 bg-gray-500 hover:bg-gray-600 disabled:opacity-50 text-white text-sm rounded transition-colors"
                >
                  <Loader2 v-if="isUploadingItemImg" :size="15" class="animate-spin" />
                  <ImagePlus v-else :size="15" />
                  新增物品影像
                </button>

                <!-- 退回單據（Create Mode 隱藏）-->
                <button
                  v-if="!isCreateMode"
                  @click="showRejectDialog = true"
                  :disabled="isSubmitting"
                  class="flex items-center gap-1.5 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm rounded font-medium transition-colors"
                >
                  <X :size="15" />
                  退回單據
                </button>

                <!-- 審核完成（Create Mode 隱藏）-->
                <button
                  v-if="!isCreateMode"
                  @click="handleApprove"
                  :disabled="isSubmitting"
                  class="flex items-center gap-1.5 px-4 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm rounded font-medium transition-colors"
                >
                  <CheckCircle2 :size="15" />
                  {{ isSubmitting ? '處理中...' : '審核完成' }}
                </button>

                <!-- 儲存 / 新增 -->
                <button
                  @click="handleSave"
                  :disabled="isSubmitting"
                  class="flex items-center gap-1.5 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 text-white text-sm rounded font-medium transition-colors"
                >
                  <Save :size="15" />
                  {{ isSubmitting ? '處理中...' : isCreateMode ? '新增' : '儲存' }}
                </button>

                <!-- 關閉 -->
                <button
                  @click="handleClose"
                  :disabled="isSubmitting"
                  class="flex items-center gap-1.5 px-4 py-2 bg-gray-400 hover:bg-gray-500 disabled:opacity-50 text-white text-sm rounded transition-colors"
                >
                  <X :size="15" />
                  關閉
                </button>
              </div>
            </div>
            <!-- /Sticky Footer -->

          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>

  <!-- ── 退回單據對話框 ────────────────────────────────────── -->
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="showRejectDialog"
        class="fixed inset-0 z-[70] flex items-center justify-center bg-black/50"
        @click.self="showRejectDialog = false"
      >
        <div class="bg-white rounded-xl p-6 w-96 shadow-2xl">
          <h3 class="text-lg font-bold text-red-600 mb-1">退回單據</h3>
          <p class="text-sm text-gray-600 mb-6">是否確認此筆單據退回並標記為作廢?</p>
          <div class="flex justify-end gap-2">
            <button
              @click="showRejectDialog = false"
              class="px-4 py-2 text-sm bg-gray-200 hover:bg-gray-300 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              @click="handleReject"
              :disabled="isSubmitting"
              class="px-4 py-2 text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg font-medium transition-colors"
            >
              {{ isSubmitting ? '處理中...' : '確認退回' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- ── 圖片放大燈箱 ──────────────────────────────────────── -->
  <Teleport to="body">
    <div
      v-if="lightboxOpen"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/80"
      @click="lightboxOpen = false"
    >
      <img
        :src="lightboxSrc"
        alt="放大影像"
        class="max-w-[90vw] max-h-[90vh] object-contain rounded shadow-2xl"
        @click.stop
      />
      <button
        @click="lightboxOpen = false"
        class="absolute top-4 right-4 text-white bg-black/50 hover:bg-black/70 rounded-full p-2 transition-colors"
      >
        <X :size="20" />
      </button>
    </div>
  </Teleport>
</template>
