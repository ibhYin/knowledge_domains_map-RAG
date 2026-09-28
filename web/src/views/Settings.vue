<template>
  <div class="page">
    <h1 class="page-title">设置</h1>
    <p class="page-desc">配置 LLM 连接信息。保存后立即生效，无需重启。其余高级设置见控制台（侧边栏底部入口）。</p>

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
      <div class="btn-row">
        <button class="btn btn-primary" @click="save">保存设置</button>
      </div>
      <div class="msg" :class="msgType" v-if="msg">{{ msg }}</div>
    </div>

    <div class="card" style="max-width:640px">
      <div class="card-title">分块参数（只读，如需调整请编辑 .env）</div>
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr);margin:0">
        <div class="stat-card"><div class="num" style="font-size:20px">{{ s.chunk_size }}</div><div class="label">分块大小（字符）</div></div>
        <div class="stat-card"><div class="num" style="font-size:20px">{{ s.chunk_overlap }}</div><div class="label">重叠</div></div>
        <div class="stat-card"><div class="num" style="font-size:20px">{{ s.extraction_concurrency }}</div><div class="label">抽取并发</div></div>
      </div>
      <p class="muted" style="margin-top:12px">结构化输出模式：{{ s.structured_output_method }}（json_mode / function_calling / json_schema）</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const baseUrl = ref('')
const apiKey = ref('')
const model = ref('')
const keySet = ref(false)
const s = ref({})
const msg = ref('')
const msgType = ref('ok')

async function load() {
  try {
    const data = await api.settings()
    baseUrl.value = data.openai_base_url || ''
    model.value = data.openai_model || ''
    keySet.value = data.api_key_set
    s.value = data
  } catch (e) {
    msg.value = '读取设置失败：' + e.message
    msgType.value = 'err'
  }
}

async function save() {
  msg.value = ''
  try {
    const r = await api.saveSettings({
      openai_base_url: baseUrl.value,
      openai_model: model.value,
      openai_api_key: apiKey.value,
    })
    apiKey.value = ''
    msg.value = r.message
    msgType.value = 'ok'
    await load()
  } catch (e) {
    msg.value = '保存失败：' + e.message
    msgType.value = 'err'
  }
}

onMounted(load)
</script>
