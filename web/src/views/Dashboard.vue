<template>
  <div class="page">
    <h1 class="page-title">首页</h1>
    <p class="page-desc">知识图谱系统总览。先上传文档、构建图谱，再开始问答。</p>

    <div class="stat-grid">
      <div class="stat-card green">
        <div class="num">{{ ov.documents ?? '—' }}</div>
        <div class="label">文档</div>
      </div>
      <div class="stat-card blue">
        <div class="num">{{ ov.chunks ?? '—' }}</div>
        <div class="label">分块</div>
      </div>
      <div class="stat-card">
        <div class="num">{{ ov.nodes ?? '—' }}</div>
        <div class="label">实体节点</div>
      </div>
      <div class="stat-card orange">
        <div class="num">{{ ov.edges ?? '—' }}</div>
        <div class="label">关系边</div>
      </div>
    </div>

    <div class="btn-row">
      <button class="btn btn-primary" @click="go('documents')">上传文档</button>
      <button class="btn btn-primary" @click="go('graph')">构建图谱</button>
      <button class="btn btn-ghost" @click="go('chat')">开始提问</button>
    </div>

    <div class="card">
      <div class="card-title">实体类型分布</div>
      <div v-if="typeStats.length" class="type-bars">
        <div v-for="t in typeStats" :key="t.type" class="type-row">
          <span class="badge" :class="badgeClass(t.type)">{{ typeCn(t.type) }}</span>
          <div class="bar-track"><div class="bar" :style="{ width: barWidth(t.count) + '%' }"></div></div>
          <span class="count">{{ t.count }}</span>
        </div>
      </div>
      <p v-else class="empty">图谱为空，尚未构建。</p>
    </div>

    <div class="card">
      <div class="card-title">关系类型分布</div>
      <div v-if="relStats.length" class="rel-chips">
        <span v-for="r in relStats" :key="r.type" class="chip">{{ relCn(r.type) }} × {{ r.count }}</span>
      </div>
      <p v-else class="empty">暂无关系。</p>
    </div>

    <div class="card">
      <div class="card-title">最近构建</div>
      <p v-if="ov.built_at" class="muted">上次构建时间：{{ ov.built_at }}</p>
      <p v-else class="empty">尚未构建过图谱。上传文档后到「图谱」页构建。</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const ov = ref({})
const emit = defineEmits(['nav'])

const TYPE_CN = { PERSON: '人物', ORG: '组织', LOCATION: '地点', CONCEPT: '概念', TIME: '时间', EVENT: '事件' }
const REL_CN = { MEMBER_OF: '隶属', AFFILIATED_WITH: '任职', FOUNDED_BY: '创建', CREATED: '提出/发布', LOCATED_IN: '位于', RELATED_TO: '相关', CAUSES: '导致', AFFECTS: '影响', PROPOSED_BY: '提出者', INVENTED_BY: '发明者', PARTNERS_WITH: '合作', USES: '使用', IN_PERIOD: '时间归属' }
const typeCn = (t) => TYPE_CN[t] || t
const relCn = (t) => REL_CN[t] || t

const typeStats = computed(() => Object.entries(ov.value.node_types || {}).map(([type, count]) => ({ type, count })))
const relStats = computed(() => Object.entries(ov.value.edge_relations || {}).map(([type, count]) => ({ type, count })))
const maxCount = computed(() => Math.max(1, ...typeStats.value.map((t) => t.count)))

function badgeClass(type) {
  return (type || 'UNKNOWN').toLowerCase()
}
function barWidth(count) {
  return Math.round((count / maxCount.value) * 100)
}
function go(key) {
  emit('nav', key)
}

onMounted(async () => {
  try {
    ov.value = await api.overview()
  } catch (e) {
    /* ignore */
  }
})
</script>

<style scoped>
.type-bars { display: flex; flex-direction: column; gap: 10px; }
.type-row { display: flex; align-items: center; gap: 12px; }
.type-row .bar-track { flex: 1; height: 8px; background: var(--border); border-radius: 999px; overflow: hidden; }
.type-row .bar { height: 100%; background: linear-gradient(90deg, var(--primary), #8b5cf6); border-radius: 999px; }
.type-row .count { width: 32px; text-align: right; color: var(--text-2); font-size: 13px; }
.rel-chips { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
