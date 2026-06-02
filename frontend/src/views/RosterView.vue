<script setup>
import { ref, computed, onMounted } from 'vue'
import { Plus, Upload, FileDown, Loader2, UserCheck, UserX, Pencil, Trash2, Link2Off } from 'lucide-vue-next'
import ConfirmModal from '../components/ConfirmModal.vue'
import {
  getRosterList,
  createRosterEntry,
  updateRosterEntry,
  deleteRosterEntry,
  importRosterCSV,
  unbindRosterEntry,
  downloadRosterTemplate,
} from '../api/rosterApi'

// ── 組別選項（與 LINE Bot Onboarding 一致） ──────────────────────
const DEPARTMENTS = [
  '製片組', '攝影組', '燈光組', '美術組', '道具組',
  '服裝組', '化妝組', '剪接組', '音效組', '行政組',
]

// ── 狀態 ─────────────────────────────────────────────────────────
const roster = ref([])
const isLoading = ref(false)
const toast = ref(null)           // { type: 'success' | 'error' | 'warn', message: string }
let toastTimer = null

// 分頁
const currentPage = ref(0)        // 後端以 0 為起始頁
const pageSize = ref(20)
const totalCount = ref(0)

// 篩選（'all' | 'bound' | 'unbound'）
const bindFilter = ref('all')

// CSV 匯入：隱藏的 file input
const fileInputRef = ref(null)
const isImporting = ref(false)

// ── Modal：新增 / 編輯 ────────────────────────────────────────────
const showFormModal = ref(false)
const isEditMode = ref(false)
const isSaving = ref(false)
const editingId = ref(null)
const form = ref({ name: '', department: '', employee_id: '' })
const formError = ref('')

// ── Confirm Dialog：刪除 ──────────────────────────────────────────
const deleteTarget = ref(null)    // { id, name }
const showDeleteConfirm = ref(false)
const isDeleting = ref(false)

// ── Confirm Dialog：解除綁定 ─────────────────────────────────────
const unbindTarget = ref(null)    // { id, name }
const showUnbindConfirm = ref(false)
const isUnbinding = ref(false)

// ── CSV 匯入結果 Modal ────────────────────────────────────────────
const showImportResult = ref(false)
const importResultData = ref(null)  // { created, updated, errors: [{row, reason}] }

// ── Computed ─────────────────────────────────────────────────────
const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize.value)))

// 分頁按鈕清單（含省略號）；數字為 1-based 頁碼，'...' 為分隔符
const pageButtons = computed(() => {
  const total = totalPages.value
  const cur = currentPage.value + 1  // 轉為 1-based

  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)

  const show = new Set([1, total, cur])
  if (cur > 1) show.add(cur - 1)
  if (cur < total) show.add(cur + 1)

  const sorted = [...show].sort((a, b) => a - b)
  const result = []
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) result.push('...')
    result.push(sorted[i])
  }
  return result
})

// ── Toast 工具 ────────────────────────────────────────────────────
function showToast(type, message, duration = 4000) {
  clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, duration)
}

// ── 資料載入 ─────────────────────────────────────────────────────
async function fetchRoster(page = currentPage.value) {
  isLoading.value = true
  try {
    const params = { page, size: pageSize.value }
    if (bindFilter.value === 'bound') params.is_bound = true
    if (bindFilter.value === 'unbound') params.is_bound = false
    const res = await getRosterList(params)
    const { content, total_elements } = res.data.data
    roster.value = content
    totalCount.value = total_elements
    currentPage.value = page
  } catch (err) {
    showToast('error', '無法載入名冊，請確認後端服務是否運行中')
    console.error('[RosterView] fetchRoster 失敗：', err)
  } finally {
    isLoading.value = false
  }
}

function changeFilter(val) {
  bindFilter.value = val
  fetchRoster(0)
}

function goToPage(page) {
  if (page < 0 || page >= totalPages.value) return
  fetchRoster(page)
}

// ── 新增 / 編輯 Modal ─────────────────────────────────────────────
function openCreateModal() {
  isEditMode.value = false
  editingId.value = null
  form.value = { name: '', department: '', employee_id: '' }
  formError.value = ''
  showFormModal.value = true
}

function openEditModal(entry) {
  isEditMode.value = true
  editingId.value = entry.id
  form.value = {
    name: entry.name || '',
    department: entry.department || '',
    employee_id: entry.employee_id || '',
  }
  formError.value = ''
  showFormModal.value = true
}

function closeFormModal() {
  showFormModal.value = false
}

async function handleSave() {
  if (!form.value.name.trim()) {
    formError.value = '姓名為必填欄位'
    return
  }
  if (!form.value.department) {
    formError.value = '請選擇組別'
    return
  }
  isSaving.value = true
  formError.value = ''
  try {
    const payload = {
      name: form.value.name.trim(),
      department: form.value.department,
      // 始終送出 employee_id：有值則更新，空字串轉 null 表示清除
      employee_id: form.value.employee_id.trim() || null,
    }

    if (isEditMode.value) {
      await updateRosterEntry(editingId.value, payload)
      showToast('success', `✅ 員工「${payload.name}」已更新`)
    } else {
      await createRosterEntry(payload)
      showToast('success', `✅ 員工「${payload.name}」已新增`)
    }
    closeFormModal()
    await fetchRoster(currentPage.value)
  } catch (err) {
    const detail = err.response?.data?.detail || err.response?.data?.message || '操作失敗，請稍後再試'
    formError.value = detail
    console.error('[RosterView] handleSave 失敗：', err)
  } finally {
    isSaving.value = false
  }
}

// ── 刪除 ─────────────────────────────────────────────────────────
function confirmDelete(entry) {
  deleteTarget.value = { id: entry.id, name: entry.name }
  showDeleteConfirm.value = true
}

async function handleDelete() {
  if (!deleteTarget.value) return
  isDeleting.value = true
  try {
    await deleteRosterEntry(deleteTarget.value.id)
    showToast('success', `✅ 已刪除員工「${deleteTarget.value.name}」`)
    showDeleteConfirm.value = false
    deleteTarget.value = null
    await fetchRoster(currentPage.value)
  } catch (err) {
    showDeleteConfirm.value = false
    const detail = err.response?.data?.detail || err.response?.data?.message || '刪除失敗'
    showToast('error', `❌ ${detail}`)
    console.error('[RosterView] handleDelete 失敗：', err)
  } finally {
    isDeleting.value = false
  }
}

// ── 解除綁定 ─────────────────────────────────────────────────────
function confirmUnbind(entry) {
  unbindTarget.value = { id: entry.id, name: entry.name }
  showUnbindConfirm.value = true
}

async function handleUnbind() {
  if (!unbindTarget.value) return
  isUnbinding.value = true
  try {
    await unbindRosterEntry(unbindTarget.value.id)
    showToast('success', `✅ 已解除「${unbindTarget.value.name}」的 LINE 綁定`)
    showUnbindConfirm.value = false
    unbindTarget.value = null
    await fetchRoster(currentPage.value)
  } catch (err) {
    showUnbindConfirm.value = false
    const detail = err.response?.data?.detail || err.response?.data?.message || '解除綁定失敗'
    showToast('error', `❌ ${detail}`)
    console.error('[RosterView] handleUnbind 失敗：', err)
  } finally {
    isUnbinding.value = false
  }
}

// ── CSV 匯入 ─────────────────────────────────────────────────────
function triggerImport() {
  fileInputRef.value?.click()
}

async function handleFileSelected(event) {
  const file = event.target.files?.[0]
  if (!file) return
  // 重置 input，讓同一個檔案可以重複選取
  event.target.value = ''

  isImporting.value = true
  try {
    const res = await importRosterCSV(file)
    const data = res.data?.data || {}
    importResultData.value = {
      created: data.created ?? 0,
      updated: data.updated ?? 0,
      errors: data.errors ?? [],
    }
    showImportResult.value = true
    await fetchRoster(0)
  } catch (err) {
    const detail = err.response?.data?.detail || err.response?.data?.message || 'CSV 匯入失敗，請確認格式是否正確'
    showToast('error', `❌ ${detail}`)
    console.error('[RosterView] importRosterCSV 失敗：', err)
  } finally {
    isImporting.value = false
  }
}

// ── 格式化日期 ────────────────────────────────────────────────────
function formatDate(dateStr) {
  if (!dateStr) return '—'
  try {
    // 若字串不帶時區資訊，補上 Z（視為 UTC）以確保本地時間轉換正確
    const normalized = /[Zz]|[+-]\d{2}:?\d{2}$/.test(dateStr) ? dateStr : dateStr + 'Z'
    const d = new Date(normalized)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const h = String(d.getHours()).padStart(2, '0')
    const min = String(d.getMinutes()).padStart(2, '0')
    return `${y}-${m}-${day} ${h}:${min}`
  } catch {
    return dateStr
  }
}

onMounted(() => fetchRoster(0))
</script>

<template>
  <div class="min-h-screen bg-gray-50">

    <!-- ── Toast 通知 ─────────────────────────────────────────── -->
    <Transition name="toast">
      <div
        v-if="toast"
        class="fixed top-4 right-4 z-50 max-w-sm px-4 py-3 rounded-lg shadow-lg text-sm font-medium flex items-start gap-2"
        :class="{
          'bg-green-50 border border-green-200 text-green-800': toast.type === 'success',
          'bg-red-50 border border-red-200 text-red-700': toast.type === 'error',
          'bg-amber-50 border border-amber-200 text-amber-800': toast.type === 'warn',
        }"
      >
        <span class="flex-1">{{ toast.message }}</span>
        <button class="opacity-60 hover:opacity-100 ml-1 leading-none" @click="toast = null">×</button>
      </div>
    </Transition>

    <!-- ── 頁面頂部工具列 ──────────────────────────────────────── -->
    <div class="px-4 pt-4 pb-3 flex items-center gap-2 flex-wrap">

      <!-- 左側操作按鈕 -->
      <button
        @click="openCreateModal"
        class="flex items-center gap-1.5 px-3 py-1.5 border border-gray-400 rounded-full text-sm text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <Plus :size="14" />
        新增員工
      </button>

      <button
        @click="triggerImport"
        :disabled="isImporting"
        class="flex items-center gap-1.5 px-3 py-1.5 border border-gray-400 rounded-full text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-60 transition-colors"
      >
        <Loader2 v-if="isImporting" :size="14" class="animate-spin" />
        <Upload v-else :size="14" />
        {{ isImporting ? '匯入中...' : '匯入 CSV' }}
      </button>
      <!-- 隱藏的 file input -->
      <input
        ref="fileInputRef"
        type="file"
        accept=".csv"
        class="hidden"
        @change="handleFileSelected"
      />

      <button
        @click="downloadRosterTemplate"
        class="flex items-center gap-1.5 px-3 py-1.5 border border-gray-400 rounded-full text-sm text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <FileDown :size="14" />
        下載樣板
      </button>

      <!-- 右側篩選按鈕組 -->
      <div class="ml-auto flex items-center gap-1 bg-gray-100 rounded-full p-0.5">
        <button
          v-for="opt in [
            { label: '全部', value: 'all' },
            { label: '已綁定', value: 'bound' },
            { label: '未綁定', value: 'unbound' },
          ]"
          :key="opt.value"
          @click="changeFilter(opt.value)"
          class="px-3 py-1 rounded-full text-sm transition-colors"
          :class="bindFilter === opt.value
            ? 'bg-white shadow text-gray-800 font-medium'
            : 'text-gray-500 hover:text-gray-700'"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>

    <!-- ── 載入中 ──────────────────────────────────────────────── -->
    <div v-if="isLoading" class="px-4 pb-2 flex items-center gap-2 text-sm text-gray-500">
      <Loader2 :size="16" class="animate-spin" />
      載入中...
    </div>

    <!-- ── 表格 ───────────────────────────────────────────────── -->
    <div class="px-4 pb-6">
      <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">

        <!-- 空狀態 -->
        <div v-if="!isLoading && roster.length === 0" class="py-16 text-center text-gray-400">
          <p class="text-sm">尚未匯入員工名冊，請點擊「匯入 CSV」開始</p>
        </div>

        <!-- 資料表格 -->
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
              <th class="px-4 py-2.5 font-medium">姓名</th>
              <th class="px-4 py-2.5 font-medium">組別</th>
              <th class="px-4 py-2.5 font-medium">員工編號</th>
              <th class="px-4 py-2.5 font-medium">綁定狀態</th>
              <th class="px-4 py-2.5 font-medium">綁定時間</th>
              <th class="px-4 py-2.5 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="entry in roster"
              :key="entry.id"
              class="border-b border-gray-100 hover:bg-gray-50 transition-colors"
            >
              <td class="px-4 py-3 font-medium text-gray-800">{{ entry.name }}</td>
              <td class="px-4 py-3 text-gray-600">{{ entry.department || '—' }}</td>
              <td class="px-4 py-3 text-gray-500 font-mono text-xs">{{ entry.employee_id || '—' }}</td>
              <td class="px-4 py-3">
                <span
                  v-if="entry.is_bound"
                  class="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800"
                >✅ 已綁定</span>
                <span
                  v-else
                  class="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600"
                >⏳ 未綁定</span>
              </td>
              <td class="px-4 py-3 text-gray-500 text-xs">{{ formatDate(entry.bound_at) }}</td>
              <td class="px-4 py-3">
                <div class="flex items-center justify-end gap-1.5">
                  <!-- 編輯 -->
                  <button
                    @click="openEditModal(entry)"
                    class="flex items-center gap-1 px-2 py-1 rounded text-xs text-blue-600 hover:bg-blue-50 transition-colors"
                    title="編輯員工資料"
                  >
                    <Pencil :size="12" />
                    編輯
                  </button>
                  <!-- 解除綁定（已綁定才顯示） -->
                  <button
                    v-if="entry.is_bound"
                    @click="confirmUnbind(entry)"
                    class="flex items-center gap-1 px-2 py-1 rounded text-xs text-amber-600 hover:bg-amber-50 transition-colors"
                    title="解除 LINE 綁定"
                  >
                    <Link2Off :size="12" />
                    解除綁定
                  </button>
                  <!-- 刪除 -->
                  <button
                    @click="confirmDelete(entry)"
                    class="flex items-center gap-1 px-2 py-1 rounded text-xs text-red-500 hover:bg-red-50 transition-colors"
                    title="刪除員工"
                  >
                    <Trash2 :size="12" />
                    刪除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 分頁 -->
        <div
          v-if="!isLoading && totalCount > 0"
          class="flex items-center justify-between px-3 py-2.5 border-t border-gray-200 bg-white text-sm"
        >
          <!-- 左側：總數 + 每頁筆數 -->
          <div class="flex items-center gap-2 text-gray-500">
            <select
              :value="pageSize"
              @change="pageSize = Number($event.target.value); fetchRoster(0)"
              class="border border-gray-300 rounded px-2 py-1 text-sm bg-white cursor-pointer"
            >
              <option v-for="s in [20, 50, 100]" :key="s" :value="s">{{ s }}</option>
            </select>
            <span>entries per page</span>
            <span class="text-gray-400 ml-2">共 {{ totalCount }} 筆</span>
          </div>

          <!-- 右側：頁碼（含省略號） -->
          <div class="flex items-center gap-1">
            <button
              @click="goToPage(currentPage - 1)"
              :disabled="currentPage === 0"
              class="w-7 h-7 flex items-center justify-center rounded border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
            >‹</button>

            <template v-for="(item, idx) in pageButtons" :key="idx">
              <span
                v-if="item === '...'"
                class="w-7 h-7 flex items-center justify-center text-gray-400 text-xs select-none"
              >…</span>
              <button
                v-else
                @click="goToPage(item - 1)"
                class="w-7 h-7 flex items-center justify-center rounded border text-xs transition-colors"
                :class="currentPage === item - 1
                  ? 'bg-blue-500 border-blue-500 text-white font-medium'
                  : 'border-gray-300 text-gray-600 hover:bg-gray-100'"
              >{{ item }}</button>
            </template>

            <button
              @click="goToPage(currentPage + 1)"
              :disabled="currentPage >= totalPages - 1"
              class="w-7 h-7 flex items-center justify-center rounded border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
            >›</button>
          </div>
        </div>

      </div>
    </div>

    <!-- ── 新增 / 編輯 Modal ──────────────────────────────────── -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showFormModal"
          class="fixed inset-0 z-50 flex items-center justify-center"
          aria-modal="true"
          role="dialog"
        >
          <!-- 遮罩 -->
          <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" @click="closeFormModal" />

          <!-- 卡片 -->
          <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4">
            <h3 class="text-gray-900 font-semibold text-lg mb-5">
              {{ isEditMode ? '編輯員工資料' : '新增員工' }}
            </h3>

            <form @submit.prevent="handleSave" class="space-y-4">
              <!-- 姓名 -->
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">
                  姓名 <span class="text-red-500">*</span>
                </label>
                <input
                  v-model="form.name"
                  type="text"
                  placeholder="王小明"
                  class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                />
              </div>

              <!-- 組別 -->
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">
                  組別 <span class="text-red-500">*</span>
                </label>
                <select
                  v-model="form.department"
                  class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                >
                  <option value="" disabled>請選擇組別</option>
                  <option v-for="dept in DEPARTMENTS" :key="dept" :value="dept">{{ dept }}</option>
                </select>
              </div>

              <!-- 員工編號（選填） -->
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">
                  員工編號
                  <span class="text-gray-400 font-normal text-xs ml-1">（選填）</span>
                </label>
                <input
                  v-model="form.employee_id"
                  type="text"
                  placeholder="EMP001"
                  class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                />
                <p class="mt-1 text-xs text-gray-400">作為員工在 LINE Bot 輸入的識別碼</p>
              </div>

              <!-- 錯誤訊息 -->
              <p v-if="formError" class="text-xs text-red-500">{{ formError }}</p>

              <!-- 按鈕列 -->
              <div class="flex gap-3 pt-1">
                <button
                  type="button"
                  @click="closeFormModal"
                  class="flex-1 px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-medium hover:bg-gray-50 transition-colors"
                >
                  取消
                </button>
                <button
                  type="submit"
                  :disabled="isSaving"
                  class="flex-1 px-4 py-2 rounded-lg bg-blue-500 hover:bg-blue-600 disabled:opacity-60 text-white text-sm font-medium transition-colors flex items-center justify-center gap-1.5"
                >
                  <Loader2 v-if="isSaving" :size="14" class="animate-spin" />
                  {{ isSaving ? '儲存中...' : '儲存' }}
                </button>
              </div>
            </form>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ── 刪除確認 Dialog ────────────────────────────────────── -->
    <ConfirmModal
      :open="showDeleteConfirm"
      :title="`確定刪除 ${deleteTarget?.name}？`"
      description="此操作不可復原。"
      confirm-text="確定刪除"
      @confirm="handleDelete"
      @cancel="showDeleteConfirm = false"
    />

    <!-- ── 解除綁定確認 Dialog ────────────────────────────────── -->
    <ConfirmModal
      :open="showUnbindConfirm"
      :title="`確定解除 ${unbindTarget?.name} 的 LINE 綁定？`"
      description="對方下次互動需重新輸入員工編號。"
      confirm-text="確定解除"
      @confirm="handleUnbind"
      @cancel="showUnbindConfirm = false"
    />

    <!-- ── CSV 匯入結果 Modal ────────────────────────────────── -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showImportResult && importResultData"
          class="fixed inset-0 z-50 flex items-center justify-center"
          aria-modal="true"
          role="dialog"
        >
          <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" @click="showImportResult = false" />
          <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-lg mx-4">
            <h3 class="text-gray-900 font-semibold text-lg mb-4">CSV 匯入結果</h3>

            <!-- 統計摘要 -->
            <div class="flex gap-4 mb-4">
              <div class="flex-1 bg-green-50 border border-green-200 rounded-lg px-3 py-2 text-center">
                <div class="text-xl font-bold text-green-700">{{ importResultData.created }}</div>
                <div class="text-xs text-green-600 mt-0.5">新增</div>
              </div>
              <div class="flex-1 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-center">
                <div class="text-xl font-bold text-blue-700">{{ importResultData.updated }}</div>
                <div class="text-xs text-blue-600 mt-0.5">更新</div>
              </div>
              <div class="flex-1 rounded-lg px-3 py-2 text-center"
                :class="importResultData.errors.length > 0
                  ? 'bg-red-50 border border-red-200'
                  : 'bg-gray-50 border border-gray-200'"
              >
                <div class="text-xl font-bold"
                  :class="importResultData.errors.length > 0 ? 'text-red-600' : 'text-gray-400'"
                >{{ importResultData.errors.length }}</div>
                <div class="text-xs mt-0.5"
                  :class="importResultData.errors.length > 0 ? 'text-red-500' : 'text-gray-400'"
                >錯誤</div>
              </div>
            </div>

            <!-- 錯誤明細（有錯誤才顯示） -->
            <div v-if="importResultData.errors.length > 0">
              <p class="text-sm font-medium text-red-600 mb-2">錯誤明細：</p>
              <ul class="max-h-48 overflow-y-auto space-y-1 border border-red-100 rounded-lg p-2 bg-red-50">
                <li
                  v-for="err in importResultData.errors"
                  :key="err.row"
                  class="text-xs text-red-700 flex gap-2"
                >
                  <span class="font-mono text-red-400 shrink-0">第 {{ err.row }} 行</span>
                  <span>{{ err.reason }}</span>
                </li>
              </ul>
            </div>

            <div class="mt-5 flex justify-end">
              <button
                @click="showImportResult = false"
                class="px-4 py-2 rounded-lg bg-gray-900 hover:bg-gray-700 text-white text-sm font-medium transition-colors"
              >
                確認
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
