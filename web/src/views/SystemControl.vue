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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const msg = ref('')
const msgType = ref('ok')
const saving = ref(false)
const baseUrl = ref('')
const apiKey = ref('')
const model = ref('')
const keySet = ref(false)

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

onMounted(loadSettings)
</script>
