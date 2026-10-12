<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'

import { createCustomer, getCustomerDetail, updateCustomer } from '@/api/modules/customer'
import PageContainer from '@/components/PageContainer/index.vue'
import { rules } from '@/utils/validate'

const route = useRoute()
const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)
const submitting = ref(false)

const customerId = computed(() => Number(route.params.id || 0))
const isEdit = computed(() => Boolean(customerId.value))

const form = reactive({
  customerCode: '',
  customerName: '',
  customerShortName: '',
  countryCode: 'CN',
  contactName: '',
  contactPhone: '',
  contactEmail: '',
  address: '',
  sourceType: '',
  ownerUserName: '当前用户'
})

const formRules = {
  customerCode: [rules.required('客户编码')],
  customerName: [rules.required('客户名称')],
  countryCode: [rules.required('国家 / 地区')],
  contactName: [rules.required('联系人')],
  contactPhone: [rules.required('联系电话'), rules.phone()],
  contactEmail: [rules.required('邮箱'), rules.email()]
}

async function loadDetail() {
  if (!isEdit.value) return

  loading.value = true
  try {
    const detail = await getCustomerDetail(customerId.value)
    Object.assign(form, detail)
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (isEdit.value) {
      await updateCustomer(customerId.value, form)
      ElMessage.success('客户已更新')
      router.push(`/customers/${customerId.value}`)
      return
    }

    const detail = await createCustomer(form)
    ElMessage.success('客户已创建')
    router.replace(`/customers/${detail.customerId}`)
  } finally {
    submitting.value = false
  }
}

onMounted(loadDetail)
</script>

<template>
  <PageContainer
    :title="isEdit ? '编辑客户' : '新建客户'"
    description="按 Customer 对象统一维护客户来源、联系人和后续协同入口。"
  >
    <section class="page-panel" v-loading="loading">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px">
        <div class="detail-grid">
          <div>
            <el-form-item label="客户编码" prop="customerCode">
              <el-input v-model="form.customerCode" />
            </el-form-item>
            <el-form-item label="客户名称" prop="customerName">
              <el-input v-model="form.customerName" />
            </el-form-item>
            <el-form-item label="客户简称">
              <el-input v-model="form.customerShortName" />
            </el-form-item>
            <el-form-item label="国家 / 地区" prop="countryCode">
              <el-input v-model="form.countryCode" />
            </el-form-item>
            <el-form-item label="来源类型">
              <el-input v-model="form.sourceType" placeholder="例如 客户定制 / 渠道客户 / 内部来源" />
            </el-form-item>
          </div>

          <div>
            <el-form-item label="联系人" prop="contactName">
              <el-input v-model="form.contactName" />
            </el-form-item>
            <el-form-item label="联系电话" prop="contactPhone">
              <el-input v-model="form.contactPhone" />
            </el-form-item>
            <el-form-item label="邮箱" prop="contactEmail">
              <el-input v-model="form.contactEmail" />
            </el-form-item>
            <el-form-item label="地址">
              <el-input v-model="form.address" type="textarea" :rows="3" />
            </el-form-item>
          </div>
        </div>

        <div class="toolbar-actions">
          <el-button @click="router.back()">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
        </div>
      </el-form>
    </section>
  </PageContainer>
</template>
