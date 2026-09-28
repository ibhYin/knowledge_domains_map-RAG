<template>
  <div class="view">
    <h2>知识图谱</h2>
    <div class="actions">
      <button :disabled="building" @click="startBuild">
        {{ building ? '构建中…' : '构建图谱' }}
      </button>
      <button class="danger" @click="clearGraph">清空图谱</button>
    </div>
    <div v-if="job" class="progress">
      {{ job.status === 'done' ? '构建完成' : job.status === 'error' ? '构建失败' : '构建中' }}：
      已处理 {{ job.processed }} / {{ job.total }} 个分块
      <span v-if="job.failed">（失败 {{ job.failed }}）</span>
      <span v-if="job.error" class="error-text">{{ job.error }}</span>
    </div>

    <div v-if="stats.nodes" class="stats-grid">
      <div class="stat-card">
        <div class="num">{{ stats.nodes }}</div>
        <div class="label">实体节点</div>
      </div>
      <div class="stat-card">
        <div class="num">{{ stats.edges }}</div>
        <div class="label">关系边</div>
      </div>
      <div v-if="stats.built_at" class="stat-card wide">
        <div class="num small">{{ stats.built_at }}</div>
        <div class="label">上次构建时间</div>
      </div>
    </div>

    <div v-if="typeStats.length" class="type-list">
      <span v-for="t in typeStats" :key="t.type" class="type-chip">
        {{ typeCn(t.type) }} {{ t.count }}
      </span>
    </div>

    <h3>图谱可视化（点击节点高亮邻居）</h3>
    <GraphViz :nodes="viz.nodes" :links="viz.links" height="600px" v-if="viz.nodes.length" />
    <p v-else class="empty">图谱为空，请先上传文档并构建图谱。</p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import GraphViz from '../components/GraphViz.vue'

const building = ref(false)
const job = ref(null)
const stats = ref({})
const viz = ref({ nodes: [], links: [] })
let pollTimer = null

const TYPE_CN = { PERSON: '人物', ORG: '组织', LOCATION: '地点', CONCEPT: '概念', TIME: '时间', EVENT: '事件' }
const typeCn = (t) => TYPE_CN[t] || t

const typeStats = computed(() =>
  Object.entries(stats.value.node_types || {}).map(([type, count]) => ({ type, count })),
)

async function refresh() {
  try {
    stats.value = await api.graphStats()
    const data = await api.graphViz()
    viz.value = data
  } catch (err) {
    alert(`获取图谱失败：${err.message}`)
  }
}

async function startBuild() {
  building.value = true
  job.value = { status: 'running', processed: 0, total: 0 }
  try {
    const { job_id } = await api.buildGraph()
    await poll(job_id)
  } catch (err) {
    job.value = { status: 'error', error: err.message }
    building.value = false
  }
}

async function poll(jobId) {
  job.value = await api.buildStatus(jobId)
  if (job.value.status === 'running') {
    pollTimer = setTimeout(() => poll(jobId), 1500)
  } else {
    building.value = false
    await refresh()
  }
}

async function clearGraph() {
  if (!confirm('确定清空图谱与全部数据？')) return
  await api.clearGraph()
  stats.value = {}
  viz.value = { nodes: [], links: [] }
  job.value = null
}

onMounted(refresh)
</script>

<style scoped>
.actions { display: flex; gap: 12px; margin: 12px 0; }
button { background: #2563eb; color: #fff; border: none; border-radius: 6px; padding: 8px 16px; cursor: pointer; font-size: 14px; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
.danger { background: #fff; color: #dc2626; border: 1px solid #fca5a5; }
.progress { margin: 10px 0; color: #2563eb; }
.error-text { color: #dc2626; margin-left: 8px; }
.stats-grid { display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }
.stat-card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 22px; text-align: center; min-width: 110px; }
.stat-card.wide { min-width: 220px; }
.num { font-size: 28px; font-weight: 700; color: #2563eb; }
.num.small { font-size: 16px; line-height: 28px; }
.label { color: #6b7280; font-size: 13px; margin-top: 4px; }
.type-list { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.type-chip { background: #eff6ff; color: #1d4ed8; border-radius: 999px; padding: 4px 12px; font-size: 13px; }
.empty { color: #999; }
</style>
