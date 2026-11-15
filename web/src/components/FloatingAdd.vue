<template>
  <!--
    右下角悬浮「新建」：顶栏那个小 + 在手机上一只手够不着，挪到拇指区。
    位置抬到底部导航之上（bottom-20），别把「课表 / 日程 / 设置」压住。
    「可办」页上同一个圆钮换成极简新建：只填标题 + 备注。
  -->
  <button
    class="fixed bottom-20 right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full
           bg-brand-600 text-white transition
           hover:bg-brand-700 active:scale-95 sm:bottom-6 sm:right-6"
    :style="{ boxShadow: '0 10px 26px -4px rgba(var(--brand-500), 0.42)' }"
    :title="isTodoView ? '新建可办事项' : '新建日程'"
    :aria-label="isTodoView ? '新建可办事项' : '新建日程'"
    :data-testid="isTodoView ? 'fab-new-todo' : 'fab-new-event'"
    @click="onClick"
  >
    <Plus :size="24" />
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { Plus } from 'lucide-vue-next'
import { openCustomEditor, openTodoQuickAdd, state } from '../store'

const isTodoView = computed(() => state.view === 'todo' || state.view === 'history')

function onClick() {
  if (isTodoView.value) openTodoQuickAdd()
  else openCustomEditor()
}
</script>
