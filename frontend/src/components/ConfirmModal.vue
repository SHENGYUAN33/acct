<script setup>
import { AlertTriangle } from 'lucide-vue-next'

const props = defineProps({
  open: {
    type: Boolean,
    required: true,
  },
  title: {
    type: String,
    default: '確定要刪除嗎？',
  },
  description: {
    type: String,
    default: '此操作無法復原，請確認後繼續。',
  },
  confirmText: {
    type: String,
    default: '確定刪除',
  },
})

const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="props.open"
        class="fixed inset-0 z-50 flex items-center justify-center"
        aria-modal="true"
        role="dialog"
      >
        <!-- 遮罩 -->
        <div
          class="absolute inset-0 bg-black/50 backdrop-blur-sm"
          @click="emit('cancel')"
        />

        <!-- 卡片 -->
        <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-sm mx-4">
          <!-- 警告 Icon -->
          <div class="flex justify-center mb-4">
            <div class="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center">
              <AlertTriangle :size="24" class="text-amber-500" />
            </div>
          </div>

          <!-- 標題 -->
          <h3 class="text-center text-gray-900 font-semibold text-lg mb-2">
            {{ props.title }}
          </h3>

          <!-- 說明文字 -->
          <p class="text-center text-gray-500 text-sm mb-6">
            {{ props.description }}
          </p>

          <!-- 按鈕列 -->
          <div class="flex gap-3">
            <button
              class="flex-1 px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-medium hover:bg-gray-50 transition-colors"
              @click="emit('cancel')"
            >
              取消
            </button>
            <button
              class="flex-1 px-4 py-2 rounded-lg bg-red-500 hover:bg-red-600 text-white text-sm font-medium transition-colors"
              @click="emit('confirm')"
            >
              {{ props.confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
