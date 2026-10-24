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
        <button v-if="job?.status === 'unknown'" class="btn btn-ghost" @click="restoreBuild">重连进度</button>
        <button class="btn btn-danger" :disabled="building" @click="clearGraph">清空图谱</button>
      </div>

      <div v-if="job" style="margin-top:14px">
        <div v-if="job.total" class="card-title">构建进度 {{ progressWidth }}% · 成功 {{ job.processed - (job.failed || 0) }} · 失败 {{ job.failed || 0 }}</div>
        <div class="progress-track">
          <div class="progress-bar" :style="{ width: progressWidth + '%' }"></div>
        </div>
        <div class="muted" role="status" aria-live="polite">
          <template v-if="job.status === 'running'">正在抽取实体关系：已处理 {{ job.processed }} / {{ job.total }} 个分块…</template>
          <template v-else-if="job.status === 'done'">
            <template v-if="job.total">构建完成：成功处理 {{ job.processed }} 个分块。</template>
            {{ job.message }}
          </template>
          <template v-else-if="job.status === 'partial'">部分完成：成功 {{ job.processed - job.failed }} / {{ job.total }} 个分块，失败 {{ job.failed }} 个。{{ job.message }}</template>
          <template v-else-if="job.status === 'error'"><span class="error-text">构建失败：{{ job.error }}</span></template>
          <template v-else-if="job.status === 'unknown'"><span class="error-text">状态获取中断：{{ job.error }}</span></template>
          <template v-else-if="job.status === 'missing'"><span class="error-text">任务已不存在，服务可能已重启。请重新构建图谱。</span></template>
          <p v-if="job.status === 'running'" style="margin:6px 0 0">进度每 1.5 秒刷新；模型请求较慢或正在重试时，数字可能暂时不变。最近获取进度：{{ lastPolledAt || '等待响应' }}</p>
        </div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="num">{{ job?.status === 'running' ? (job.nodes ?? (stats.nodes || '等待发布')) : (stats.nodes ?? '—') }}</div>
        <div class="label">{{ job?.status === 'running' ? '构建中实体（含暂存）' : '实体节点' }}</div>
      </div>
      <div class="stat-card orange">
        <div class="num">{{ job?.status === 'running' ? (job.edges ?? (stats.edges || '等待发布')) : (stats.edges ?? '—') }}</div>
        <div class="label">{{ job?.status === 'running' ? '构建中关系（含暂存）' : '关系边' }}</div>
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
      <p v-else-if="building" class="empty">图谱正在构建，实体与关系将在结果保存后显示。请查看上方处理进度。</p>
      <p v-else class="empty">图谱为空。请先在「文档」页上传文档，再点击上方「构建图谱」。</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import GraphViz from '../components/GraphViz.vue'

const building = ref(false)
const job = ref(null)
const stats = ref({})
const viz = ref({ nodes: [], links: [] })
const activeJobId = ref(null)
const JOB_KEY = 'graphrag.buildJobId'
const lastPolledAt = ref('')
const emit = defineEmits(['build-progress'])
watch(job, (state) => emit('build-progress', state), { flush: 'sync' })
let pollTimer = null
let disposed = false
let savedCheckpoint = 0

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
  if (building.value) return
  savedCheckpoint = 0
  building.value = true
  job.value = { status: 'running', processed: 0, total: 0 }
  try {
    const { job_id } = await api.buildGraph()
    activeJobId.value = job_id
    localStorage.setItem(JOB_KEY, job_id)
    if (!disposed) await poll(job_id)
  } catch (e) {
    if (disposed) return
    job.value = { status: 'error', error: e.message }
    building.value = false
  }
}

async function poll(jobId) {
  clearTimeout(pollTimer)
  if (job.value?.status === 'unknown') job.value = { ...job.value, status: 'running' }
  try {
    const state = await api.buildStatus(jobId)
    if (disposed) return
    job.value = state
    lastPolledAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    if (state.checkpoint_processed > savedCheckpoint) {
      savedCheckpoint = state.checkpoint_processed
      await refresh()
    }
    if (state.status === 'running') {
      pollTimer = setTimeout(() => poll(jobId), 1500)
    } else {
      building.value = false
      await refresh()
    }
  } catch (e) {
    if (disposed) return
    if (e.status === 404) {
      localStorage.removeItem(JOB_KEY)
      activeJobId.value = null
      job.value = { status: 'missing' }
      building.value = false
    } else {
      job.value = { ...job.value, status: 'unknown', error: `${e.message}。任务可能仍在后台运行，请重连进度。` }
      building.value = true
    }
  }
}

async function clearGraph() {
  if (building.value || !confirm('确定清空图谱？已上传的文档和分块会保留。')) return
  await api.clearGraph()
  stats.value = {}
  viz.value = { nodes: [], links: [] }
  job.value = null
  activeJobId.value = null
  localStorage.removeItem(JOB_KEY)
}

async function restoreBuild() {
  const url = new URL(window.location.href)
  const linkedJobId = url.searchParams.get('build_job')
  let savedJobId = linkedJobId || localStorage.getItem(JOB_KEY) || document.querySelector('meta[name="graphrag-build-job"]')?.content
  try {
    const current = await api.currentBuild()
    if (current.job_id) savedJobId = current.job_id
  } catch (e) {
    if (e.status !== 404 && !savedJobId) {
      building.value = true
      job.value = { status: 'unknown', error: `无法查询当前任务：${e.message}，请重连进度。` }
      return
    }
  }
  if (disposed) return
  if (savedJobId && /^[a-f0-9]{12}$/.test(savedJobId)) {
    if (savedJobId !== activeJobId.value) savedCheckpoint = 0
    activeJobId.value = savedJobId
    localStorage.setItem(JOB_KEY, savedJobId)
    building.value = true
    job.value = { status: 'running', processed: 0, total: 0 }
    await poll(savedJobId)
  }
  if (linkedJobId) {
    url.searchParams.delete('build_job')
    window.history.replaceState(null, '', url)
  }
  await refresh()
}

onMounted(restoreBuild)
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(pollTimer)
})
</script>

<style scoped>
.type-legend { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
</style>
