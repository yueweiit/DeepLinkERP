<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getSystemRoles } from '@/api/modules/system'
import type { PilotRoleDefinition } from '@/types/pilot'
import { pilotRoleNames } from '@/types/pilot'
import PageContainer from '@/components/PageContainer/index.vue'
const roles=ref<PilotRoleDefinition[]>([]),error=ref('')
onMounted(async()=>{try{roles.value=await getSystemRoles()}catch{error.value='固定角色查询失败'}})
</script>
<template><PageContainer title="试点固定角色" description="一期不创建任意角色。在账号与权限页配置真实账号、对象范围及角色内独立权限。"><el-alert v-if="error" :title="error" type="error"/><el-table :data="roles" border><el-table-column label="角色" width="160"><template #default="{row}">{{pilotRoleNames[row.roleCode as keyof typeof pilotRoleNames]}}</template></el-table-column><el-table-column label="可授权操作"><template #default="{row}"><el-tag v-for="p in row.permissions" :key="p" class="permission">{{p}}</el-tag></template></el-table-column></el-table></PageContainer></template>
<style scoped>.permission{margin:5px}</style>
