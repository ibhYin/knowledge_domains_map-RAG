<template>
  <div class="page">
    <h1 class="page-title">图谱浏览器</h1>
    <p class="page-desc">搜索实体查看详情与其关联，或在两个实体之间查找关联路径。</p>

    <div class="card">
      <div class="search-row">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" /></svg>
        <input v-model="query" placeholder="输入实体名称，如：星辰科技 / 李华" @input="onSearch" @keydown.enter="doSearch" />
      </div>
      <div v-if="results.length" class="result-list">
        <div
          v-for="r in results"
          :key="r.id"
          class="result-item"
          :class="{ active: selected?.id === r.id }"
          @click="select(r)"
        >
          <span class="badge" :class="badgeClass(r.type)">{{ typeCn(r.type) }}</span>
          <span class="name">{{ r.name }}</span>
          <span class="muted" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.description }}</span>
          <span class="muted">×{{ r.mention_count }}</span>
        </div>
      </div>
      <p v-else-if="queried" class="empty">未找到匹配实体。</p>
    </div>

    <div v-if="selected" class="detail-grid">
      <div class="card">
        <div class="card-title" style="display:flex;align-items:center;gap:10px">
          <span class="badge" :class="badgeClass(selected.type)">{{ typeCn(selected.type) }}</span>
          <span style="font-size:16px">{{ selected.name }}</span>
          <span class="muted">出现 {{ selected.mention_count }} 次</span>
        </div>
        <p v-if="selected.description">{{ selected.description }}</p>
        <p v-if="selected.aliases?.length" class="muted">别名：{{ selected.aliases.join('、') }}</p>
        <p v-if="selected.source_docs?.length" class="muted">来源文档：{{ selected.source_docs.join('、') }}</p>

        <div class="card-title" style="margin-top:18px">关联实体（{{ selected.neighbors?.length || 0 }}）</div>
        <div v-if="selected.neighbors?.length" class="neighbor-list">
          <div v-for="(n, i) in selected.neighbors" :key="i" class="neighbor-item">
            <span class="arrow">{{ n.direction === 'in' ? '←' : '→' }}</span>
            <span>{{ n.node }}</span>
            <span class="chip green">{{ relCn(n.relation) }}</span>
          </div>
        </div>
        <p v-else class="empty">该实体暂无关联。</p>
        <GraphViz v-if="detailViz.links.length" :nodes="detailViz.nodes" :links="detailViz.links" height="360px" />
      </div>

      <div class="card">
        <div class="card-title">路径查询</div>
        <div class="field">
          <label>起点实体</label>
          <input v-model="pathFrom" placeholder="输入起点，如：李华" />
        </div>
        <div class="field">
          <label>终点实体</label>
          <input v-model="pathTo" placeholder="输入终点，如：北京" />
        </div>
        <button class="btn btn-primary" @click="findPath">查找路径</button>

        <div v-if="pathResult" class="path-result">
          <div v-if="pathResult.nodes" class="path-chain">
            <template v-for="(n, i) in pathResult.nodes" :key="i">
              <span class="path-node">{{ n }}</span>
              <span v-if="i < pathResult.nodes.length - 1" class="path-arrow">→</span>
            </template>
          </div>
          <GraphViz v-if="pathViz.links.length" :nodes="pathViz.nodes" :links="pathViz.links" height="300px" />
          <p v-if="pathError" class="error-text">{{ pathError }}</p>
        </div>
      </div>
    </div>

    <div v-else class="card">
      <p class="empty">搜索并选择一个实体，查看其详情、关联与路径。</p>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import GraphViz from '../components/GraphViz.vue'

const query = ref('')
const results = ref([])
const queried = ref(false)
const selected = ref(null)
const pathFrom = ref('')
const pathTo = ref('')
const pathResult = ref(null)
const pathError = ref('')
let searchTimer = null

const TYPE_CN = { PERSON: '人物', ORG: '组织', LOCATION: '地点', CONCEPT: '概念', TIME: '时间', EVENT: '事件' }
const REL_CN = { MEMBER_OF: '隶属', AFFILIATED_WITH: '任职', FOUNDED_BY: '创建', CREATED: '提出/发布', LOCATED_IN: '位于', RELATED_TO: '相关', CAUSES: '导致', AFFECTS: '影响', PROPOSED_BY: '提出者', INVENTED_BY: '发明者', PARTNERS_WITH: '合作', USES: '使用', IN_PERIOD: '时间归属' }
const typeCn = (t) => TYPE_CN[t] || t
const relCn = (t) => REL_CN[t] || t
const badgeClass = (t) => (t || 'UNKNOWN').toLowerCase()

const detailViz = computed(() => {
  if (!selected.value) return { nodes: [], links: [] }
  const nodes = [{ id: selected.value.id, name: selected.value.name, type: selected.value.type, description: selected.value.description, mention_count: selected.value.mention_count }]
  const links = []
  for (const n of selected.value.neighbors || []) {
    if (!nodes.some((x) => x.id === n.node)) {
      nodes.push({ id: n.node, name: n.node, type: 'UNKNOWN', description: '', mention_count: 0 })
    }
    links.push({
      source: n.direction === 'in' ? n.node : selected.value.id,
      target: n.direction === 'in' ? selected.value.id : n.node,
      relation: n.relation,
      weight: n.weight,
    })
  }
  return { nodes, links }
})

const pathViz = computed(() => {
  if (!pathResult.value?.nodes) return { nodes: [], links: [] }
  const nodes = pathResult.value.nodes.map((id) => ({ id, name: id, type: 'UNKNOWN', description: '', mention_count: 0 }))
  return { nodes, links: pathResult.value.links.map((l) => ({ ...l, weight: 1 })) }
})

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(doSearch, 300)
}
async function doSearch() {
  const q = query.value.trim()
  if (!q) {
    results.value = []
    queried.value = false
    return
  }
  try {
    const data = await api.entitySearch(q)
    results.value = data.results
    queried.value = true
  } catch (e) {
    results.value = []
  }
}

async function select(r) {
  selected.value = null
  try {
    selected.value = await api.entityDetail(r.id)
  } catch (e) {
    alert('加载详情失败：' + e.message)
  }
}

async function findPath() {
  pathResult.value = null
  pathError.value = ''
  const from = pathFrom.value.trim() || selected.value?.id
  const to = pathTo.value.trim()
  if (!from || !to) {
    pathError.value = '请输入起点与终点实体'
    return
  }
  try {
    const data = await api.findPath(from, to)
    pathResult.value = data
  } catch (e) {
    pathError.value = e.message
  }
}
</script>

<style scoped>
.search-row { display: flex; align-items: center; gap: 10px; border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; color: var(--text-3); }
.search-row input { flex: 1; border: none; outline: none; font-size: 14.5px; }
.result-list { margin-top: 10px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.result-item { display: flex; align-items: center; gap: 10px; padding: 9px 12px; cursor: pointer; border-bottom: 1px solid var(--border); font-size: 13.5px; }
.result-item:last-child { border-bottom: none; }
.result-item:hover { background: var(--bg); }
.result-item.active { background: var(--primary-50); }
.result-item .name { font-weight: 500; }
.detail-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 16px; align-items: start; }
.neighbor-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.neighbor-item { display: inline-flex; align-items: center; gap: 6px; background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 5px 10px; font-size: 13px; }
.neighbor-item .arrow { color: var(--text-3); }
.path-result { margin-top: 14px; }
.path-chain { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 13.5px; }
.path-node { background: var(--primary-50); color: var(--primary); border-radius: 6px; padding: 4px 10px; font-weight: 500; }
.path-arrow { color: var(--text-3); }
@media (max-width: 900px) { .detail-grid { grid-template-columns: 1fr; } }
</style>
