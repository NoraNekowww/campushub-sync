<template>
  <!--
    右下角悬浮「新建」：顶栏那个小 + 在手机上一只手够不着，挪到拇指区。
    位置抬到底部导航之上（bottom-20），别把「课表 / 日程 / 设置」压住。
  -->
  <button
    class="fixed bottom-20 right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full
           bg-brand-600 text-white shadow-lg shadow-brand-600/30 transition
           hover:bg-brand-700 active:scale-95 sm:bottom-6 sm:right-6"
    title="新建日程"
    aria-label="新建日程"
    data-testid="fab-new-event"
    @click="openCustomEditor()"
  >
    <Plus :size="24" />
  </button>
</template>

<script setup>
import { Plus } from 'lucide-vue-next'
import { openCustomEditor } from '../store'
</script>
