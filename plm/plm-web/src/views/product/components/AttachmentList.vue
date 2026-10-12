<script setup lang="ts">
import type { ProductAttachment } from '@/types/product'
import { formatDateTime } from '@/utils/format'

defineProps<{ rows: ProductAttachment[]; editable?: boolean }>()
</script>

<template>
  <el-table :data="rows" border stripe>
    <el-table-column prop="fileName" label="文件名" min-width="240" />
    <el-table-column prop="fileCategory" label="类型" width="140" />
    <el-table-column prop="versionNo" label="版本" width="90" />
    <el-table-column prop="uploadedBy" label="上传人" width="120" />
    <el-table-column label="上传时间" width="180">
      <template #default="{ row }">{{ formatDateTime(row.uploadedAt) }}</template>
    </el-table-column>
    <el-table-column label="状态" width="120">
      <template #default="{ row }"><el-tag effect="light">{{ row.status }}</el-tag></template>
    </el-table-column>
  </el-table>
</template>
