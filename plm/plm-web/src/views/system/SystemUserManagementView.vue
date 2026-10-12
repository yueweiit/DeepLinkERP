<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemUsers, getSystemRoles, saveSystemUser, getSystemScopeOptions } from '@/api/modules/system'
import PageContainer from '@/components/PageContainer/index.vue'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import type { PilotUser, PilotUserInput, PilotRoleDefinition, PilotEntity } from '@/types/pilot'
import { pilotRoleNames } from '@/types/pilot'
const users=ref<PilotUser[]>([]),roles=ref<PilotRoleDefinition[]>([]),loading=ref(false),saving=ref(false),drawer=ref(false),keyword=ref(''),editing=ref<number|null>(null)
const error=ref(''),scopeType=ref<PilotEntity>('mold'),scopeSearch=ref(''),scopeId=ref<number|null>(null),scopeOptions=ref<{id:number;label:string}[]>([])
const form=reactive<PilotUserInput>({username:'',displayName:'',departmentName:'',roleCode:'domestic',status:'active',allObjects:true,dingtalkUserId:'',permissions:[],fieldGroups:[],scopes:[],password:'',beforeVersion:null})
const filtered=computed(()=>users.value.filter(u=>[u.username,u.displayName,u.departmentName].join(' ').toLowerCase().includes(keyword.value.trim().toLowerCase())))
const administrator=computed(()=>form.roleCode==='administrator')
const external=computed(()=>['supplier','mexico'].includes(form.roleCode))
const rolePermissionOptions=computed(()=>roles.value.find(r=>r.roleCode===form.roleCode)?.permissions||[])
const groups:Record<string,string>={market:'市场',engineering:'工程',logistics:'物流',mexico:'墨西哥',production:'产量'}
const entityNames:Record<string,string>={item:'协作档案',mold:'模具套',product:'产品项目',file:'文件附件'}
async function load(){loading.value=true;error.value='';try{[users.value,roles.value]=await Promise.all([getSystemUsers(),getSystemRoles()])}catch{error.value='真实账号加载失败，请重试'}finally{loading.value=false}}
function setRole(){form.permissions=[...rolePermissionOptions.value];form.allObjects=!external.value;form.fieldGroups=administrator.value?Object.keys(groups):form.roleCode==='supplier'?['engineering','logistics']:form.roleCode==='mexico'?['mexico']:form.roleCode==='domestic'?['market','engineering','logistics','production']:[]}
function open(user?:PilotUser){editing.value=user?.userId||null;Object.assign(form,{username:user?.username||'',displayName:user?.displayName||'',departmentName:user?.departmentName||'',roleCode:user?.allPermissions?'administrator':user?.roleCode||'domestic',status:user?.status||'active',allObjects:user?.allObjects??true,dingtalkUserId:user?.dingtalkUserId||'',permissions:[...(user?.permissions||[])],fieldGroups:[...(user?.fieldGroups||[])],scopes:user?.scopes.map(s=>({...s}))||[],password:'',beforeVersion:user?.version||null});if(administrator.value||!user?.roleCode)setRole();scopeId.value=null;scopeOptions.value=[];drawer.value=true}
async function searchScopes(){scopeOptions.value=await getSystemScopeOptions(scopeType.value,scopeSearch.value)}
function addScope(){if(scopeId.value&&!form.scopes.some(s=>s.entityType===scopeType.value&&s.entityId===scopeId.value))form.scopes.push({entityType:scopeType.value,entityId:scopeId.value})}
async function save(){if(!form.username.trim()||!form.displayName.trim()||!form.departmentName.trim())return ElMessage.warning('请填写账号、姓名和部门');if(!editing.value&&form.password.length<12)return ElMessage.warning('新账号密码至少12位');saving.value=true;try{await saveSystemUser(editing.value,{...form,allObjects:external.value?false:form.allObjects});form.password='';drawer.value=false;await load();ElMessage.success('真实账号与授权已保存')}catch{error.value='保存失败或授权已被他人修改，请核对后重试'}finally{saving.value=false}}
onMounted(load)
</script>
<template>
 <PageContainer title="账号与权限" description="复用真实登录账号；固定试点角色、字段职责、独立金额操作及逐对象授权。">
  <template #actions><el-button @click="load">刷新</el-button><el-button type="primary" @click="open()">新增真实账号</el-button></template>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <el-input v-model="keyword" placeholder="搜索真实账号 / 姓名 / 部门" clearable/>
  <FixedTableViewport v-slot="{tableHeight}" :refresh-key="filtered"><el-table :data="filtered" :height="tableHeight" v-loading="loading" border>
   <el-table-column prop="username" label="登录账号" min-width="160"/><el-table-column prop="displayName" label="姓名" width="140"/><el-table-column prop="departmentName" label="部门" min-width="160"/>
   <el-table-column label="固定角色" width="140"><template #default="{row}">{{row.allPermissions?'管理员':row.roleCode?pilotRoleNames[row.roleCode as keyof typeof pilotRoleNames]:'历史兼容账号'}}</template></el-table-column>
   <el-table-column prop="status" label="启用状态" width="100"/><el-table-column label="对象范围" min-width="190"><template #default="{row}">{{row.allObjects||row.allPermissions?'全部授权对象':row.scopes.length+' 个指定对象'}}</template></el-table-column>
   <el-table-column label="操作" width="140" fixed="right"><template #default="{row}"><el-button link type="primary" @click="open(row)">编辑 / 授权</el-button></template></el-table-column>
  </el-table></FixedTableViewport>
  <el-drawer v-model="drawer" :title="editing?'编辑真实账号与授权':'新增真实账号'" size="min(1000px,95vw)" :close-on-click-modal="false">
   <el-form label-position="top" class="account-form">
    <el-form-item label="登录账号（创建后固定）"><el-input v-model="form.username" :disabled="!!editing" autocomplete="off"/></el-form-item>
    <el-form-item label="姓名"><el-input v-model="form.displayName"/></el-form-item><el-form-item label="部门 / 公司"><el-input v-model="form.departmentName"/></el-form-item>
    <el-form-item label="固定角色"><el-select v-model="form.roleCode" @change="setRole"><el-option v-for="r in roles" :key="r.roleCode" :value="r.roleCode" :label="pilotRoleNames[r.roleCode]"/></el-select></el-form-item>
    <el-alert v-if="administrator" class="wide" type="info" :closable="false" title="管理员拥有全部对象、所有字段、全部金额操作及账号配置权限；要收权请先切换为其他固定角色。"/>
    <el-form-item label="启用 / 停用"><el-select v-model="form.status"><el-option value="active" label="启用"/><el-option value="inactive" label="停用（已有会话亦失效）"/></el-select></el-form-item>
    <el-form-item :label="editing?'重设密码（留空不修改）':'初始密码（至少12位）'"><el-input v-model="form.password" type="password" show-password autocomplete="new-password"/></el-form-item>
    <el-form-item label="真实钉钉 UserID（管理员核对映射）"><el-input v-model="form.dingtalkUserId"/></el-form-item>
    <el-form-item v-if="!external" label="对象范围"><el-checkbox v-model="form.allObjects" :disabled="administrator">{{administrator?'全部对象（管理员固定）':'全部对象（国内 / 财务）'}}</el-checkbox></el-form-item>
    <el-form-item label="独立操作权限" class="wide"><el-checkbox-group v-model="form.permissions" :disabled="administrator"><el-checkbox v-for="p in rolePermissionOptions" :key="p" :value="p">{{p}}</el-checkbox></el-checkbox-group><small>{{administrator?'管理员的 * 表示全部权限，不能通过取消勾选收权。':'金额查看、编辑、确认、导出可分别取消，不能超出固定角色。'}}</small></el-form-item>
    <el-form-item label="字段填写职责" class="wide"><el-checkbox-group v-model="form.fieldGroups" :disabled="administrator"><el-checkbox v-for="(label,g) in groups" :key="g" :value="g">{{label}}</el-checkbox></el-checkbox-group><small>{{administrator?'管理员可填写所有字段组，固定角色切换后才可配置较小职责范围。':'供应商工程 / 物流；墨西哥仅签收验收，仍受手机动作白名单限制。'}}</small></el-form-item>
    <el-form-item label="指定对象授权（附件须逐份开放）" class="wide"><div class="scope-picker"><el-select v-model="scopeType" :disabled="administrator" @change="scopeOptions=[];scopeId=null"><el-option v-for="(label,v) in entityNames" :key="v" :value="v" :label="label"/></el-select><el-input v-model="scopeSearch" :disabled="administrator" placeholder="搜索名称或编码" @keyup.enter="searchScopes"/><el-button :disabled="administrator" @click="searchScopes">查询</el-button></div><div class="scope-picker"><el-select v-model="scopeId" :disabled="administrator" placeholder="选择真实对象" filterable><el-option v-for="o in scopeOptions" :key="o.id" :value="o.id" :label="o.label"/></el-select><el-button :disabled="administrator" @click="addScope">加入授权</el-button></div><el-tag v-for="(s,index) in form.scopes" :key="s.entityType+'-'+s.entityId" :closable="!administrator" @close="form.scopes.splice(index,1)">{{entityNames[s.entityType]}} #{{s.entityId}}</el-tag><small v-if="administrator">管理员访问全部对象及附件，已有指定对象记录不限制其访问。</small></el-form-item>
   </el-form><template #footer><el-button @click="drawer=false;form.password=''">取消未保存修改</el-button><el-button type="primary" :loading="saving" @click="save">保存真实账号与授权</el-button></template>
  </el-drawer>
 </PageContainer>
</template>
<style scoped>.account-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 24px}.wide{grid-column:1/-1}.scope-picker{display:flex;gap:8px;width:100%;margin-bottom:10px}.scope-picker .el-select{min-width:180px;flex:1}.el-tag{margin:4px}.el-checkbox-group{display:flex;gap:8px;flex-wrap:wrap}small{display:block;color:#64748b;line-height:1.6}@media(max-width:650px){.account-form{grid-template-columns:1fr}.scope-picker{flex-wrap:wrap}}</style>
