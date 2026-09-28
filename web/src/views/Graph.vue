<template>
  <div class="page">
    <h1 class="page-title">知识图谱</h1>
    <p class="page-desc">用 LLM 从文档抽取实体与关系构建知识图谱，支持增量更新。</p>

    <div class="card">
      <div class="btn-row" style="margin:0">
        <button class="btn btn-success" :disabled="building" @click="startBuild">
          {{ building ? '构建中…' : '构建图谱' }}
        </button>
        <button class="btn btn-ghost" @click="refresh">刷新统计</button>
        <button class="btn btn-danger" @click="clearGraph">清空图谱</button>
      </div>

      <div v-if="job" style="margin-top:14px">
        <div class="progress-track">
          <div class="progress-bar" :style="{ width: progressWidth + '%' }"></div>
        </div>
        <div class="muted">
          <template v-if="job.status === 'running'">正在抽取实体关系：已处理 {{ job.processed }} / {{ job.total }} 个分块…</template>
          <template v-else-if="job.status === 'done'">构建完成：处理 {{ job.processed }} 个分块<span v-if="job.failed">（失败 {{ job.failed }}）</span></template>
          <template v-else-if="job.status === 'error'"><span class="error-text">构建失败：{{ job.error }}</span></template>
        </div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="num">{{ stats.nodes ?? '—' }}</div>
        <div class="label">实体节点</div>
      </div>
      <div class="stat-card orange">
        <div class="num">{{ stats.edges ?? '—' }}</div>
        <div class="label">关系边</div>
      </div>
      <div class="stat-card green" v-if="stats.built_at">
        <div class="num" style="font-size:15px;line-height:28px">{{ stats.built_at }}</div>
        <div class="label">上次构建</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">图谱可视化</div>
      <div class="type-legend">
        <span v-for="t in typeStats" :key="t.type" class="chip">{{ typeCn(t.type) }} {{ t.count }}</span>
      </div>
      <GraphViz v-if="viz.nodes.length" :nodes="viz.nodes" :links="viz.links" height="600px" />
      <p v-else class="empty">图谱为空。请先在「文档」页上传文档，再点击上方「构建图谱」。</p>
    </div>
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

const typeStats = computed(() => Object.entries(stats.value.node_types || {}).map(([type, count]) => ({ type, count })))
const progressWidth = computed(() => {
  if (!job.value || !job.value.total) return 0
  return Math.min(100, Math.round((job.value.processed / job.value.total) * 100))
})

async function refresh() {
  try {
    stats.value = await api.graphStats()
    viz.value = await api.graphViz()
  } catch (e) {
    /* ignore */
  }
}

async function startBuild() {
  building.value = true
  job.value = { status: 'running', processed: 0, total: 0 }
  try {
    const { job_id } = await api.buildGraph()
    await poll(job_id)
  } catch (e) {
    job.value = { status: 'error', error: e.message }
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
.type-legend { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
</style>
