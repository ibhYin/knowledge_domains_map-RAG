<template>
  <div class="page">
    <h1 class="page-title">模型设置</h1>
    <p class="page-desc">配置实体抽取与问答使用的模型。保存后，新建的模型请求会使用最新设置。</p>

    <div class="card" style="max-width:640px">
      <div class="card-title">LLM 配置</div>
      <div class="field">
        <label for="llm-base-url">请求地址 base_url</label>
        <input id="llm-base-url" v-model="baseUrl" placeholder="https://xxx/v1" />
      </div>
      <div class="field">
        <label for="llm-api-key">API Key</label>
        <input id="llm-api-key" v-model="apiKey" type="password" placeholder="留空表示保持不变" autocomplete="off" />
        <div class="hint">{{ keySet ? '已设置 API Key（输入新值可覆盖，留空保留原值）' : '尚未设置 API Key' }}</div>
      </div>
      <div class="field">
        <label for="llm-model">模型名称</label>
        <input id="llm-model" v-model="model" placeholder="例如 deepseek-chat / qwen-max" />
      </div>
      <button class="btn btn-primary" :disabled="saving" @click="saveSettings">{{ saving ? '保存中…' : '保存设置' }}</button>
      <div v-if="msg" class="msg" :class="msgType" role="status">{{ msg }}</div>
    </div>

    <div class="card" style="max-width:640px">
      <div class="card-title">运行状态</div>
      <table class="data-table">
        <tbody>
          <tr>
            <td>后端 PID</td>
            <td>{{ health.pid ?? '—' }}</td>
          </tr>
          <tr>
            <td>启动时间</td>
            <td>{{ health.started_at ?? '—' }}</td>
          </tr>
          <tr>
            <td>代码更新时间</td>
            <td>{{ health.code_mtime || '—' }}</td>
          </tr>
          <tr>
            <td>自动重载</td>
            <td>
              <span v-if="!control" class="hint" style="margin: 0">控制服务未运行{{ statusError ? `：${statusError}` : '' }}</span>
              <span v-else-if="!control.autoreload_enabled" class="hint" style="margin: 0">已关闭（BACKEND_AUTORELOAD=0）</span>
              <span v-else-if="control.pending_reload" style="color: var(--danger)">已开启 · 有代码变更，等待构建结束后重载</span>
              <span v-else style="color: var(--success)">已开启 · 每 {{ control.autoreload_interval }} 秒检查源码</span>
            </td>
          </tr>
          <tr v-if="control && control.port_busy">
            <td>接管提示</td>
            <td>当前后端（PID {{ control.port_pid }}）不由控制服务管理，首次代码变更时会自动接管；也可执行 <code>./start.sh restart</code> 立即接管。</td>
          </tr>
          <tr v-if="control && control.last_reload_at">
            <td>最近重载</td>
            <td>{{ control.last_reload_at }} · {{ control.last_reload_message }}</td>
          </tr>
        </tbody>
      </table>
      <div class="hint" style="margin-top: 10px">
        后端源码变更后自动重载，构建进行中会延后到任务结束。页面无需刷新；只有改前端代码并重新构建时才需要刷新页面。
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'

const msg = ref('')
const msgType = ref('ok')
const saving = ref(false)
const baseUrl = ref('')
const apiKey = ref('')
const model = ref('')
const keySet = ref(false)

const health = ref({})
const control = ref(null)
const statusError = ref('')
let statusTimer = null

function showMsg(text, ok = true) {
  msg.value = text
  msgType.value = ok ? 'ok' : 'err'
}

async function loadSettings() {
  try {
    const s = await api.settings()
    baseUrl.value = s.openai_base_url || ''
    model.value = s.openai_model || ''
    keySet.value = s.api_key_set
  } catch (e) {
    showMsg('读取设置失败：' + e.message, false)
  }
}

async function saveSettings() {
  if (saving.value) return
  saving.value = true
  try {
    const r = await api.saveSettings({ openai_base_url: baseUrl.value, openai_model: model.value, openai_api_key: apiKey.value })
    apiKey.value = ''
    showMsg(r.message)
    await loadSettings()
  } catch (e) {
    showMsg('保存失败：' + e.message, false)
  } finally {
    saving.value = false
  }
}

async function loadStatus() {
  try {
    health.value = await api.health()
  } catch {
    health.value = {}
  }
  try {
    control.value = await api.controlStatus()
    statusError.value = ''
  } catch (e) {
    control.value = null
    statusError.value = e.message
  }
}

onMounted(() => {
  loadSettings()
  loadStatus()
  statusTimer = setInterval(loadStatus, 10000)
})

onUnmounted(() => clearInterval(statusTimer))
</script>
