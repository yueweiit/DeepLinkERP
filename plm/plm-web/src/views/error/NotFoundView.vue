<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="error-shell">
    <section class="page-panel error-panel">
      <h1>404</h1>
      <p>页面不存在，可能已经被移动或路径输入有误。</p>
      <el-button type="primary" @click="router.push('/dashboard')">返回工作台</el-button>
    </section>
  </div>
</template>

<style scoped>
.error-shell {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 24px;
}

.error-panel {
  width: min(420px, 100%);
  text-align: center;
}

.error-panel h1 {
  margin: 0 0 12px;
  font-size: 56px;
}

.error-panel p {
  margin: 0 0 20px;
  color: var(--plm-color-text-secondary);
}
</style>
