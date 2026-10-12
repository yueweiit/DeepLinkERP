<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { CodeItem, CodeItemPayload } from '@/api/modules/code'

const props = defineProps<{ modelValue: boolean; item?: CodeItem | null; loading?: boolean; codeType?: 'color' | 'phone_model' }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'save', payload: CodeItemPayload): void }>()
const form = reactive<CodeItemPayload>({ codeType: 'color', codeValue: '', codeName: '', codeNameZh: '', sortOrder: 0 })
const isPhone = computed(() => form.codeType === 'phone_model')
const typeLabel = computed(() => isPhone.value ? '手机型号编码' : '颜色编码')
const valid = computed(() => Boolean(form.codeName.trim()) && (isPhone.value ? /^[0-9]{4}$/.test(form.codeValue) : Boolean(form.codeValue.trim())))

watch(() => [props.modelValue, props.item], () => {
  if (!props.modelValue) return
  form.codeType = props.item?.codeType || props.codeType || 'color'
  form.codeValue = props.item?.codeValue || ''
  form.codeName = props.item?.codeName || ''
  form.codeNameZh = props.item?.codeNameZh || ''
  form.sortOrder = props.item?.sortOrder || 0
}, { immediate: true })
</script>

<template>
  <el-dialog :model-value="modelValue" :title="`${item ? '编辑' : '新增'}${typeLabel}`" width="520px" @close="emit('update:modelValue', false)">
    <el-form label-position="top">
      <div class="code-form-grid">
        <el-form-item label="编码类型"><el-input :model-value="typeLabel" disabled /></el-form-item>
        <el-form-item :label="isPhone ? '型号编码（四位数字）' : '颜色编码值'"><el-input v-model="form.codeValue" :disabled="Boolean(item)" :maxlength="isPhone ? 4 : 64" :placeholder="isPhone ? '例如 0001，创建后不可修改' : '例如 02'" /></el-form-item>
      </div>
      <el-form-item :label="isPhone ? '手机型号名称' : '颜色原名称'"><el-input v-model="form.codeName" :maxlength="128" :placeholder="isPhone ? '例如 Apple iPhone 16' : '例如 Negro'" /></el-form-item>
      <el-form-item v-if="!isPhone" label="颜色中文名称"><el-input v-model="form.codeNameZh" :maxlength="128" placeholder="例如 黑色" /></el-form-item>
      <el-form-item label="排序"><el-input-number v-model="form.sortOrder" :min="0" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button data-test="save-code-item" type="primary" :loading="loading" :disabled="!valid" @click="emit('save', { ...form, codeName: form.codeName.trim() })">保存{{ typeLabel }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>.code-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; } @media (max-width: 560px) { .code-form-grid { grid-template-columns: 1fr; } }</style>
