<template>
  <div class="page">
    <h1 class="page-title">问答历史</h1>
    <p class="page-desc">查看此前的提问与回答，点击可展开检索上下文。</p>

    <div class="card">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
        <button class="btn btn-danger btn-sm" @click="clearAll" :disabled="!items.length">清空历史</button>
      </div>

      <div v-if="items.length" class="history-list">
        <div v-for="(h, i) in items" :key="i" class="history-item">
          <div class="h-head" @click="h.open = !h.open">
            <div class="h-q">{{ h.question }}</div>
            <div class="muted">{{ h.ts }} · {{ h.node_count }} 节点 / {{ h.edge_count }} 边</div>
            <svg :class="{ open: h.open }" class="chevron" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m6 9 6 6 6-6" /></svg>
          </div>
          <div v-if="h.open" class="h-body">
            <div v-if="h.matched?.length" class="meta">匹配实体：<span v-for="m in h.matched" :key="m" class="chip green">{{ m }}</span></div>
            <div class="h-answer">{{ h.answer }}</div>
            <GraphViz v-if="h.subgraph?.nodes?.length" :nodes="h.subgraph.nodes" :links="h.subgraph.links" height="300px" />
          </div>
        </div>
      </div>
      <p v-else class="empty">暂无问答记录。到「问答」页提问后会自动保存到这里。</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import GraphViz from '../components/GraphViz.vue'

const items = ref([])

async function refresh() {
  try {
    const data = await api.history()
    items.value = data.history.map((h) => ({ ...h, open: false }))
  } catch (e) {
    /* ignore */
  }
}

async function clearAll() {
  if (!confirm('确定清空全部问答历史？')) return
  await api.clearHistory()
  items.value = []
}

onMounted(refresh)
</script>

<style scoped>
.history-list { display: flex; flex-direction: column; gap: 10px; }
.history-item { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.h-head { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; }
.h-head:hover { background: #f8fafc; }
.h-q { flex: 1; font-weight: 500; }
.chevron { color: var(--text-3); transition: transform 0.2s; }
.chevron.open { transform: rotate(180deg); }
.h-body { border-top: 1px solid var(--border); padding: 14px 16px; }
.h-answer { font-size: 13.5px; line-height: 1.7; margin: 8px 0; }
.meta { font-size: 13px; color: var(--text-2); }
</style>
