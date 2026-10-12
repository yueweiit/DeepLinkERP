<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useUserStore } from '@/stores/user'
import { getPilotSsoStatus } from '@/api/modules/pilot'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const sso=ref({enabled:false,corpId:'',message:'正在读取钉钉免登配置'})
type DingApi={ready:(fn:()=>void)=>void;runtime:{permission:{requestAuthCode:(options:{corpId:string;onSuccess:(result:{code:string})=>void;onFail:()=>void})=>void}}}
async function dingApi():Promise<DingApi>{
 const current=(window as Window&{dd?:DingApi}).dd;if(current)return current
 await new Promise<void>((resolve,reject)=>{const script=document.createElement('script');script.src='https://g.alicdn.com/dingding/dingtalk-jsapi/2.0.0/dingtalk.open.js';script.onload=()=>resolve();script.onerror=()=>reject(new Error('钉钉SDK加载失败'));document.head.appendChild(script)})
 const dd=(window as Window&{dd?:DingApi}).dd;if(!dd)throw new Error('请在已配置的钉钉轻应用内免登');return dd
}
async function handleDingLogin(){loading.value=true;try{const dd=await dingApi();const code=await new Promise<string>((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('钉钉免登超时，请在应用内重试')),15000);dd.ready(()=>dd.runtime.permission.requestAuthCode({corpId:sso.value.corpId,onSuccess:r=>{clearTimeout(timer);resolve(r.code)},onFail:()=>{clearTimeout(timer);reject(new Error('钉钉免登失败，请使用网页登录'))}}))});await userStore.loginDingTalk(code);router.push(String(route.query.redirect||(userStore.hasPermission('dashboard:view')?'/dashboard':'/pilot/tasks')))}catch(error){ElMessage.error(error instanceof Error?error.message:'钉钉免登失败')}finally{loading.value=false}}
onMounted(async()=>{try{sso.value=await getPilotSsoStatus()}catch{sso.value.message='无法读取免登配置，可使用网页登录'}})

const form = reactive({
  username: import.meta.env.DEV ? 'engineer01' : '',
  password: import.meta.env.DEV ? 'plm123456' : ''
})

const development = import.meta.env.DEV
const accounts = import.meta.env.DEV ? [
  'engineer01 / plm123456 - 工程部测试账号',
  'engineer02 / plm123456 - 工程部测试账号'
] : []

async function handleLogin() {
  loading.value = true
  try {
    await userStore.login(form)
    ElMessage.success('登录成功')
    const home = userStore.hasPermission('dashboard:view') ? '/dashboard' : userStore.hasPermission('pilot:tasks') ? '/pilot/tasks' : userStore.hasPermission('collaboration:view') ? '/collaboration-plans' : '/403'
    router.push(userStore.profile?.roleCode === 'supplier' || userStore.profile?.roleCode === 'mexico' ? '/pilot/tasks' : String(route.query.redirect || home))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-shell">
    <section class="login-panel">
      <div class="login-panel__brand">
        <h1>Yuewei PLM</h1>
        <p>手机壳制造业产品研发协同系统</p>
      </div>

      <el-form :model="form" label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password @keyup.enter="handleLogin" />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="handleLogin">登录</el-button>
      </el-form>
      <p class="login-panel__tips">{{sso.message}}</p>
      <el-button :disabled="!sso.enabled" :loading="loading" style="width:100%" @click="handleDingLogin">钉钉轻应用免登</el-button>

      <div v-if="development" class="login-panel__tips">
        <strong>后端 M1 测试账号</strong>
        <ul>
          <li v-for="item in accounts" :key="item">{{ item }}</li>
        </ul>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-shell {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(64, 158, 255, 0.16), transparent 30%),
    linear-gradient(180deg, #eef4ff 0%, #f4f6f8 42%, #ebf0f7 100%);
}

.login-panel {
  width: min(440px, 100%);
  padding: 32px;
  border: 1px solid rgba(220, 223, 230, 0.9);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: var(--plm-shadow-lg);
}

.login-panel__brand h1 {
  margin: 0;
  font-size: 28px;
}

.login-panel__brand p {
  margin: 10px 0 24px;
  color: var(--plm-color-text-secondary);
}

.login-panel__tips {
  margin-top: 20px;
  color: var(--plm-color-text-secondary);
  font-size: 13px;
}

.login-panel__tips ul {
  padding-left: 18px;
}
</style>
