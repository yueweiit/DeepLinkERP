<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElDialog, ElMessage } from 'element-plus'
import { getCollaborationAssignments, saveCollaborationAssignments } from '@/api/modules/collaboration'
import type { AssignmentSettings } from '@/types/collaboration'
const props=withDefaults(defineProps<{modelValue?:boolean;pageMode?:boolean}>(),{modelValue:false,pageMode:false})
const emit=defineEmits<{ 'update:modelValue':[value:boolean]; saved:[] }>()
const visible=computed({get:()=>props.modelValue,set:value=>emit('update:modelValue',value)})
const settings=ref<AssignmentSettings>(),form=ref<AssignmentSettings['groups']>(),saving=ref(false),error=ref('')
const groupNames={market:'市场资料',engineering:'工程日期与模具',logistics:'物流日期与位置',mexico:'墨西哥签收与验收',production:'累计产量'}
async function load(){error.value='';try{settings.value=await getCollaborationAssignments();form.value=JSON.parse(JSON.stringify(settings.value.groups))}catch{error.value='职责加载失败，请重试'}}
async function save(){if(!form.value||!settings.value)return;saving.value=true;error.value='';try{settings.value=await saveCollaborationAssignments(form.value,settings.value.groups);visible.value=false;emit('saved');ElMessage.success('固定职责已保存')}catch{error.value='保存失败或职责已变化，请刷新后核对'}finally{saving.value=false}}
watch(()=>props.modelValue,value=>{if(value)void load()})
onMounted(()=>{if(props.pageMode||props.modelValue)void load()})
</script>
<template>
 <component :is="pageMode?'section':ElDialog" v-model="visible" title="协作职责" width="min(1000px,95vw)" :class="{'assignment-page':pageMode}" :close-on-click-modal="false">
  <h2 v-if="pageMode">协作职责</h2><p>同一字段组可配置多个真实账号，适用于所有档案；管理员可跨组编辑并留痕。对象范围与手机动作权限仍由账号授权控制。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <el-form v-if="form" label-position="top" class="assignment-grid"><el-form-item v-for="(name,g) in groupNames" :key="g" :label="name"><el-select v-model="form[g]" multiple filterable style="width:100%"><el-option v-for="u in settings?.users" :key="u.userId" :label="(u.displayName||u.username)+(u.allPermissions?'（管理员）':'')" :value="u.userId"/></el-select></el-form-item></el-form>
  <div class="assignment-actions"><el-button @click="pageMode?load():visible=false">{{pageMode?'刷新 / 撤销未保存':'取消'}}</el-button><el-button type="primary" :loading="saving" @click="save">保存职责</el-button></div>
 </component>
</template>
<style scoped>.assignment-page{width:100%;display:flex;flex-direction:column;gap:16px}.assignment-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.assignment-actions{display:flex;gap:12px;justify-content:flex-end}p{color:#64748b;line-height:1.7}@media(max-width:650px){.assignment-grid{grid-template-columns:1fr}}</style>
