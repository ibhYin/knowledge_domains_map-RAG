<template>
  <div class="page">
    <h1 class="page-title">系统控制</h1>
    <p class="page-desc">在此配置 LLM 并启动 / 停止系统。停止后重新启动：再次双击「启动GraphRAG.command」。</p>

    <div class="card">
      <div class="card-title">系统状态</div>
      <div class="status-row">
        <span class="dot" :class="{ running: status.backend_ready }"></span>
        <span class="status-text">
          {{ status.backend_ready ? '运行中' : status.backend_running ? '启动中…' : '已停止' }}
        </span>
        <span v-if="status.backend_running" class="muted">PID {{ status.backend_pid }} · 端口 {{ status.backend_port }}</span>
      </div>
      <div class="btn-row" style="margin:0">
        <button class="btn btn-success" :disabled="status.backend_running || busy" @click="doStart">启动系统</button>
        <button class="btn btn-danger" :disabled="!status.backend_running || busy" @click="doStop">停止系统</button>
        <button class="btn btn-ghost" :disabled="!status.backend_running || busy" @click="doRestart">重启</button>
      </div>
      <div class="msg" :class="msgType" v-if="msg">{{ msg }}</div>
    </div>

    <div class="card" style="max-width:640px">
      <div class="card-title">LLM 配置</div>
      <div class="field">
        <label>请求地址 base_url</label>
        <input v-model="baseUrl" placeholder="https://xxx/v1" />
      </div>
      <div class="field">
        <label>API Key</label>
        <input v-model="apiKey" type="password" placeholder="留空表示保持不变" autocomplete="off" />
        <div class="hint">{{ keySet ? '已设置 API Key（输入新值可覆盖，留空保留原值）' : '尚未设置 API Key' }}</div>
      </div>
      <div class="field">
        <label>模型名称</label>
        <input v-model="model" placeholder="例如 gpt-4o-mini / deepseek-chat / qwen-max" />
      </div>
      <button class="btn btn-primary" @click="saveSettings">保存设置</button>
    </div>

    <div class="card">
      <div class="card-title">后端日志</div>
      <pre ref="logBox">{{ logs }}</pre>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'

const status = ref({ backend_running: false, backend_ready: false })
const busy = ref(false)
const msg = ref('')
const msgType = ref('ok')
const baseUrl = ref('')
const apiKey = ref('')
const model = ref('')
const keySet = ref(false)
const logs = ref('（暂无日志）')
const logBox = ref(null)
let pollTimer = null
let stopped = false

function showMsg(text, ok = true) {
  msg.value = text
  msgType.value = ok ? 'ok' : 'err'
}

async function refreshStatus() {
  try {
    status.value = await api.controlStatus()
  } catch (e) {
    if (!stopped) {
      status.value = { backend_running: false, backend_ready: false }
    }
  }
}

async function refreshLogs() {
  try {
    const l = await api.controlLogs(120)
    if (l.logs) {
      logs.value = l.logs
      await nextTick()
      if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
    }
  } catch (e) {
    /* ignore */
  }
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
  try {
    const r = await api.saveSettings({ openai_base_url: baseUrl.value, openai_model: model.value, openai_api_key: apiKey.value })
    apiKey.value = ''
    showMsg(r.message)
    await loadSettings()
  } catch (e) {
    showMsg('保存失败：' + e.message, false)
  }
}

async function doStart() {
  busy.value = true
  try {
    const r = await api.controlStart()
    showMsg(r.message || '已启动')
  } catch (e) {
    showMsg('启动失败：' + e.message, false)
  } finally {
    busy.value = false
    await refreshStatus()
  }
}

async function doStop() {
  if (!confirm('确定停止系统？停止后需再次双击「启动GraphRAG.command」来重新启动。')) return
  stopped = true
  try {
    await api.controlStop()
  } catch (e) {
    /* 后端已被停止，请求失败属正常 */
  }
  alert('系统已停止。请双击「启动GraphRAG.command」重新启动。')
  window.location.href = 'about:blank'
}

async function doRestart() {
  busy.value = true
  showMsg('正在重启系统，请稍候…')
  try {
    await api.controlRestart()
  } catch (e) {
    /* 重启过程中后端进程会被替换，请求中断属正常 */
  }
  setTimeout(() => window.location.reload(), 12000)
}

onMounted(() => {
  refreshStatus()
  loadSettings()
  refreshLogs()
  pollTimer = setInterval(() => {
    refreshStatus()
    refreshLogs()
  }, 4000)
})

onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<style scoped>
.status-row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: #94a3b8; }
.dot.running { background: #22c55e; box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.15); }
.status-text { font-weight: 500; font-size: 14px; }
pre { background: #0f172a; color: #cbd5e1; border-radius: 10px; padding: 14px; font-size: 12px; line-height: 1.5; height: 260px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; margin: 0; }
</style>
