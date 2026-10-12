<script setup lang="ts">
import { computed } from 'vue'


const props = withDefaults(
  defineProps<{
    modelValue?: number | number[] | null
    multiple?: boolean
    placeholder?: string
  }>(),
  {
    modelValue: null,
    multiple: false,
    placeholder: '请选择用户'
  }
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: number | number[] | null): void
}>()

const options = computed<Array<{ userId: number; userName: string; roleName: string; department?: string }>>(() => [])
</script>

<template>
  <el-select
    :model-value="props.modelValue"
    :multiple="multiple"
    filterable
    clearable
    style="width: 100%"
    :placeholder="placeholder"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-option
      v-for="user in options"
      :key="user.userId"
      :label="`${user.userName} / ${user.roleName}`"
      :value="user.userId"
    >
      <div class="user-option">
        <span>{{ user.userName }}</span>
        <span class="user-option__meta">{{ user.department || '--' }} / {{ user.roleName }}</span>
      </div>
    </el-option>
  </el-select>
</template>

<style scoped>
.user-option {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.user-option__meta {
  color: var(--plm-color-text-secondary);
}
</style>
