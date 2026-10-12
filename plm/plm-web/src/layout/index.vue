<template>
  <div class="layout-shell">
    <Sidebar />
    <div class="layout-shell__main">
      <Navbar />
      <ContentArea />
    </div>
  </div>
</template>

<script setup lang="ts">
import ContentArea from './ContentArea.vue'
import Navbar from './Navbar.vue'
import Sidebar from './Sidebar.vue'
</script>

<style scoped>
.layout-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.layout-shell__main {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
}
</style>
