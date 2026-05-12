<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { X, Plus, Trash2, Clock, Save, Loader2 } from 'lucide-vue-next'
import { toast } from 'vue3-toastify'
import { getSchedulerConfig, updateSchedulerConfig } from '../api/expenseApi'

const emit = defineEmits(['close'])

// ── 狀態 ──────────────────────────────────────────
const isLoading = ref(true)
const isSaving = ref(false)

// 排程開關
const enabled = ref(false)

// 模式：'fixed'（固定時間點）| 'range'（時間範圍）
const mode = ref('fixed')

// 固定時間點清單
const fixedTimes = ref(['20:00'])

// 時間範圍參數
const rangeStart = ref('20:00')
const rangeEnd = ref('22:00')
const rangeInterval = ref(30)  // 分鐘

// 時區
const timezone = ref('Asia/Taipei')

// 下次執行時間（唯讀，從 API 取得）
const scheduledJobs = ref([])

// ── 常數 ──────────────────────────────────────────
const INTERVAL_OPTIONS = [
  { label: '每 15 分鐘', value: 15 },
  { label: '每 30 分鐘', value: 30 },
  { label: '每 1 小時', value: 60 },
  { label: '每 2 小時', value: 120 },
]

const TIMEZONE_OPTIONS = [
  'Asia/Taipei',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'UTC',
]

// ── 計算屬性：時間範圍預覽 ──────────────────────────
const rangePreview = computed(() => {
  const times = []
  try {
    const [sh, sm] = rangeStart.value.split(':').map(Number)
    const [eh, em] = rangeEnd.value.split(':').map(Number)
    const endMin = eh * 60 + em
    let cur = sh * 60 + sm
    if (cur > endMin || rangeInterval.value <= 0) return []
    while (cur <= endMin) {
      const h = Math.floor(cur / 60)
      const m = cur % 60
      times.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
      cur += rangeInterval.value
    }
  } catch {
    return []
  }
  return times
})

// 最終送出的時間清單
const finalTimes = computed(() =>
  mode.value === 'fixed' ? fixedTimes.value : rangePreview.value
)

// ── 載入現有設定 ───────────────────────────────────
onMounted(async () => {
  try {
    const res = await getSchedulerConfig()
    const data = res.data?.data
    if (data) {
      enabled.value = data.enabled ?? false
      timezone.value = data.timezone ?? 'Asia/Taipei'
      scheduledJobs.value = data.scheduled_jobs ?? []

      const times = data.times ?? []
      if (times.length > 0) {
        // 嘗試判斷是固定時間點還是範圍：若每個相鄰時間間隔相同 → 視為範圍
        if (times.length >= 2) {
          const diffs = []
          for (let i = 1; i < times.length; i++) {
            diffs.push(_toMinutes(times[i]) - _toMinutes(times[i - 1]))
          }
          const allSame = diffs.every(d => d === diffs[0] && d > 0)
          if (allSame) {
            mode.value = 'range'
            rangeStart.value = times[0]
            rangeEnd.value = times[times.length - 1]
            rangeInterval.value = diffs[0]
          } else {
            mode.value = 'fixed'
            fixedTimes.value = times
          }
        } else {
          mode.value = 'fixed'
          fixedTimes.value = times
        }
      }
    }
  } catch {
    toast.error('載入排程設定失敗')
  } finally {
    isLoading.value = false
  }
})

function _toMinutes(hhmm) {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

// ── 固定時間點操作 ────────────────────────────────
function addTime() {
  fixedTimes.value.push('20:00')
}

function removeTime(index) {
  fixedTimes.value.splice(index, 1)
}

function updateTime(index, value) {
  fixedTimes.value[index] = value
}

// ── 驗證 ──────────────────────────────────────────
const validationError = computed(() => {
  if (!enabled.value) return null
  if (finalTimes.value.length === 0) {
    return mode.value === 'fixed'
      ? '請至少新增一個觸發時間'
      : '時間範圍無效（開始時間須早於結束時間）'
  }
  if (mode.value === 'fixed') {
    for (const t of fixedTimes.value) {
      const parts = t.split(':')
      if (parts.length !== 2) return `時間格式錯誤：${t}`
      const [h, m] = parts.map(Number)
      if (isNaN(h) || isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59)
        return `時間超出範圍：${t}`
    }
  }
  return null
})

// ── 儲存 ──────────────────────────────────────────
async function handleSave() {
  if (validationError.value) {
    toast.error(validationError.value)
    return
  }
  if (isSaving.value) return
  isSaving.value = true
  try {
    const res = await updateSchedulerConfig({
      enabled: enabled.value,
      times: finalTimes.value,
      timezone: timezone.value,
    })
    scheduledJobs.value = res.data?.data?.scheduled_jobs ?? []
    toast.success(res.data?.message || '排程設定已儲存')
    emit('close')
  } catch (err) {
    const msg = err.response?.data?.detail || '儲存失敗，請確認後端服務是否運行中'
    toast.error(msg)
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <!-- 背景遮罩 -->
  <div
    class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
    @click.self="emit('close')"
  >
    <div class="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">

      <!-- Header -->
      <div class="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <div class="flex items-center gap-2">
          <Clock :size="18" class="text-orange-500" />
          <h2 class="text-base font-semibold text-gray-800">排程批次設定</h2>
        </div>
        <button @click="emit('close')" class="text-gray-400 hover:text-gray-600 transition-colors">
          <X :size="18" />
        </button>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="flex items-center justify-center py-16">
        <Loader2 :size="24" class="animate-spin text-gray-400" />
      </div>

      <!-- 內容 -->
      <div v-else class="px-5 py-4 space-y-5">

        <!-- 啟用開關 -->
        <div class="flex items-center justify-between py-2">
          <div>
            <p class="text-sm font-medium text-gray-700">啟用排程批次</p>
            <p class="text-xs text-gray-400 mt-0.5">停用後不影響「立即處理 Pending」按鈕</p>
          </div>
          <button
            @click="enabled = !enabled"
            :class="[
              'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
              enabled ? 'bg-orange-500' : 'bg-gray-200',
            ]"
          >
            <span
              :class="[
                'inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform',
                enabled ? 'translate-x-6' : 'translate-x-1',
              ]"
            />
          </button>
        </div>

        <!-- 以下內容：僅 enabled 時顯示 -->
        <template v-if="enabled">

          <!-- 時段模式切換 -->
          <div>
            <p class="text-sm font-medium text-gray-700 mb-2">時段模式</p>
            <div class="flex gap-2">
              <button
                @click="mode = 'fixed'"
                :class="[
                  'flex-1 py-2 rounded-lg text-sm font-medium border transition-colors',
                  mode === 'fixed'
                    ? 'bg-orange-50 border-orange-400 text-orange-600'
                    : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300',
                ]"
              >
                固定時間點
              </button>
              <button
                @click="mode = 'range'"
                :class="[
                  'flex-1 py-2 rounded-lg text-sm font-medium border transition-colors',
                  mode === 'range'
                    ? 'bg-orange-50 border-orange-400 text-orange-600'
                    : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300',
                ]"
              >
                時間範圍
              </button>
            </div>
          </div>

          <!-- 固定時間點 -->
          <div v-if="mode === 'fixed'" class="space-y-2">
            <p class="text-xs text-gray-400">可新增多個時間點，每日依序觸發</p>
            <div
              v-for="(t, i) in fixedTimes"
              :key="i"
              class="flex items-center gap-2"
            >
              <input
                type="time"
                :value="t"
                @change="updateTime(i, $event.target.value)"
                class="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-300"
              />
              <button
                @click="removeTime(i)"
                :disabled="fixedTimes.length <= 1"
                class="text-gray-300 hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <Trash2 :size="16" />
              </button>
            </div>
            <button
              @click="addTime"
              class="flex items-center gap-1.5 text-sm text-orange-500 hover:text-orange-600 transition-colors"
            >
              <Plus :size="14" />
              新增時間點
            </button>
          </div>

          <!-- 時間範圍 -->
          <div v-else class="space-y-3">
            <p class="text-xs text-gray-400">系統會在範圍內依指定間隔重複觸發</p>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs text-gray-500 mb-1">開始時間</label>
                <input
                  type="time"
                  v-model="rangeStart"
                  class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-300"
                />
              </div>
              <div>
                <label class="block text-xs text-gray-500 mb-1">結束時間</label>
                <input
                  type="time"
                  v-model="rangeEnd"
                  class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-300"
                />
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">觸發間隔</label>
              <select
                v-model="rangeInterval"
                class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-300"
              >
                <option v-for="opt in INTERVAL_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <!-- 預覽 -->
            <div v-if="rangePreview.length > 0" class="bg-orange-50 rounded-lg px-3 py-2">
              <p class="text-xs text-orange-600 font-medium mb-1">預覽觸發時間點（共 {{ rangePreview.length }} 次）</p>
              <p class="text-xs text-orange-500">{{ rangePreview.join('、') }}</p>
            </div>
            <div v-else class="bg-red-50 rounded-lg px-3 py-2">
              <p class="text-xs text-red-500">時間設定無效，請確認開始時間早於結束時間</p>
            </div>
          </div>

          <!-- 時區 -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">時區</label>
            <select
              v-model="timezone"
              class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-300"
            >
              <option v-for="tz in TIMEZONE_OPTIONS" :key="tz" :value="tz">{{ tz }}</option>
            </select>
          </div>

        </template>

        <!-- 下次執行時間（唯讀） -->
        <div v-if="scheduledJobs.length > 0" class="border-t border-gray-100 pt-4">
          <p class="text-xs font-medium text-gray-500 mb-2">目前排程（儲存前的狀態）</p>
          <div class="space-y-1">
            <div
              v-for="job in scheduledJobs"
              :key="job.id"
              class="flex items-center justify-between text-xs"
            >
              <span class="text-gray-600">{{ job.name }}</span>
              <span class="text-gray-400">
                {{ job.next_run_time ? new Date(job.next_run_time).toLocaleString('zh-TW') : '—' }}
              </span>
            </div>
          </div>
        </div>

        <!-- 錯誤提示 -->
        <div v-if="validationError" class="bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          <p class="text-xs text-red-600">{{ validationError }}</p>
        </div>

      </div>

      <!-- Footer -->
      <div class="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-100">
        <button
          @click="emit('close')"
          class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          取消
        </button>
        <button
          @click="handleSave"
          :disabled="isSaving || isLoading || !!validationError"
          class="flex items-center gap-1.5 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-60 text-white rounded-lg text-sm font-medium transition-colors"
        >
          <Loader2 v-if="isSaving" :size="14" class="animate-spin" />
          <Save v-else :size="14" />
          {{ isSaving ? '儲存中...' : '儲存設定' }}
        </button>
      </div>

    </div>
  </div>
</template>
