<script setup lang="ts">
import { reactive, watch } from 'vue'

import type { SearchField } from '@/types/common'

const props = defineProps<{
  fields: SearchField[]
  modelValue?: Record<string, unknown>
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: Record<string, unknown>): void
  (event: 'search', value: Record<string, unknown>): void
  (event: 'reset'): void
}>()

const form = reactive<Record<string, unknown>>({})

function resetLocalForm(source?: Record<string, unknown>) {
  Object.keys(form).forEach((key) => delete form[key])
  props.fields.forEach((field) => {
    form[field.prop] = source?.[field.prop] ?? ''
  })
}

watch(
  () => props.modelValue,
  (value) => resetLocalForm(value),
  { immediate: true, deep: true }
)

function handleSearch() {
  const payload = { ...form }
  emit('update:modelValue', payload)
  emit('search', payload)
}

function handleReset() {
  resetLocalForm()
  emit('update:modelValue', { ...form })
  emit('reset')
}
</script>

<template>
  <section class="search-bar page-panel">
    <el-form :model="form" inline class="search-form">
      <el-form-item v-for="field in fields" :key="field.prop" :label="field.label">
        <el-input
          v-if="field.type === 'input'"
          v-model="form[field.prop]"
          :placeholder="field.placeholder || `请输入${field.label}`"
          clearable
        />
        <el-select
          v-else-if="field.type === 'select'"
          v-model="form[field.prop]"
          :placeholder="field.placeholder || `请选择${field.label}`"
          clearable
          style="width: 180px"
        >
          <el-option
            v-for="option in field.options || []"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-date-picker
          v-else
          v-model="form[field.prop]"
          type="date"
          value-format="YYYY-MM-DD"
          :placeholder="field.placeholder || `请选择${field.label}`"
        />
      </el-form-item>

      <div v-if="$slots.extra" class="search-form__extra">
        <slot name="extra" />
      </div>

      <el-form-item class="search-form__actions">
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button @click="handleReset">重置</el-button>
      </el-form-item>
    </el-form>
  </section>
</template>

<style scoped>
.search-bar {
  padding-bottom: 4px;
}

.search-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
}

.search-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.search-form__extra {
  display: flex;
  align-items: center;
  margin-left: auto;
  margin-right: 12px;
  margin-bottom: 12px;
}

.search-form__actions {
  margin-left: 0;
}
</style>
