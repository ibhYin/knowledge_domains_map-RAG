<template>
  <div class="page">
    <h1 class="page-title">问答历史</h1>
    <p class="page-desc">查看此前的提问与回答，点击可展开检索上下文。</p>

    <div class="card">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
        <button class="btn btn-danger btn-sm" @click="clearAll" :disabled="!items.length">清空历史</button>
      </div>

      <div v-if="items.length" class="history-list">
        <div v-for="(h, i) in items" :key="h.index" class="history-item">
          <button class="h-head" :aria-expanded="h.open" :aria-controls="`history-body-${i}`" @click="toggle(h)">
            <span class="h-q">{{ h.question }}</span>
            <span class="muted">{{ h.ts }} · {{ h.node_count }} 节点 / {{ h.edge_count }} 边</span>
            <svg :class="{ open: h.open }" class="chevron" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m6 9 6 6 6-6" /></svg>
          </button>
          <div v-if="h.open" :id="`history-body-${i}`" class="h-body">
            <p v-if="!h.detail" class="muted">加载详情…</p>
            <template v-else>
              <div v-if="h.detail.matched?.length" class="meta">匹配实体：<span v-for="m in h.detail.matched" :key="m" class="chip green">{{ m }}</span></div>
              <CitedAnswer :answer="h.detail.answer" :sentences="h.detail.sentences || []" :sources="h.detail.sources || []"
                :retrieved-sources="h.detail.retrieved_sources || []" :verification="h.detail.verification || ''" />
              <GraphViz v-if="h.detail.subgraph?.nodes?.length" :nodes="h.detail.subgraph.nodes" :links="h.detail.subgraph.links" height="300px" />
            </template>
          </div>
        </div>
      </div>
      <p v-else class="empty">暂无问答记录。到「问答」页提问后会自动保存到这里。</p>

      <div v-if="items.length < total" style="text-align:center;margin-top:12px">
        <button class="btn btn-sm" @click="loadMore" :disabled="loadingMore">{{ loadingMore ? '加载中…' : '加载更多' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import GraphViz from '../components/GraphViz.vue'
import CitedAnswer from '../components/CitedAnswer.vue'

const PAGE_SIZE = 20
const items = ref([])
const total = ref(0)
const loadingMore = ref(false)

async function refresh() {
  try {
    const data = await api.history(0, PAGE_SIZE)
    total.value = data.total
    items.value = data.items.map((h) => ({ ...h, open: false, detail: null }))
  } catch (e) {
    /* ignore */
  }
}

async function toggle(h) {
  h.open = !h.open
  if (h.open && !h.detail) {
    try {
      h.detail = await api.historyDetail(h.index)
    } catch (e) {
      /* ignore */
    }
  }
}

async function loadMore() {
  loadingMore.value = true
  try {
    const data = await api.history(items.value.length, PAGE_SIZE)
    total.value = data.total
    items.value.push(...data.items.map((h) => ({ ...h, open: false, detail: null })))
  } catch (e) {
    /* ignore */
  } finally {
    loadingMore.value = false
  }
}

async function clearAll() {
  if (!confirm('确定清空全部问答历史？')) return
  await api.clearHistory()
  items.value = []
  total.value = 0
}

onMounted(refresh)
</script>

<style scoped>
.history-list { display: flex; flex-direction: column; gap: 10px; }
.history-item { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.h-head { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; width: 100%; border: 0; background: var(--surface); color: inherit; text-align: left; font: inherit; }
.h-head:hover { background: #f8fafc; }
.h-q { flex: 1; font-weight: 500; }
.chevron { color: var(--text-3); transition: transform 0.2s; }
.chevron.open { transform: rotate(180deg); }
.h-body { border-top: 1px solid var(--border); padding: 14px 16px; }
.h-answer { font-size: 13.5px; line-height: 1.7; margin: 8px 0; }
.meta { font-size: 13px; color: var(--text-2); }
</style>
