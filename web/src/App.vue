<script setup>
import { computed, markRaw, onMounted, ref } from 'vue'
import { api } from './api'
import Dashboard from './views/Dashboard.vue'
import Documents from './views/Documents.vue'
import Graph from './views/Graph.vue'
import Explorer from './views/Explorer.vue'
import Chat from './views/Chat.vue'
import History from './views/History.vue'
import SystemControl from './views/SystemControl.vue'

const navs = [
  { key: 'dashboard', label: '首页', icon: 'M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9', comp: markRaw(Dashboard) },
  { key: 'documents', label: '文档', icon: 'M6 2h8l4 4v16H6V2zm8 0v4h4M8 10h8M8 14h8M8 18h5', comp: markRaw(Documents) },
  { key: 'graph', label: '图谱', icon: 'M12 5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm-8 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm16 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM4 10v4m16-4v4M6.2 8.5 10 6m7.8 2.5L14 6m0 0a5 5 0 0 0-4 0m4 0v6m0 0a5 5 0 0 1-4 0', comp: markRaw(Graph) },
  { key: 'explorer', label: '图谱浏览器', icon: 'M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm-2-8h4m-2-2v4', comp: markRaw(Explorer) },
  { key: 'chat', label: '问答', icon: 'M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.7A8 8 0 1 1 21 12zM8.5 10h7m-7 4h4', comp: markRaw(Chat) },
  { key: 'history', label: '问答历史', icon: 'M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0z', comp: markRaw(History) },
  { key: 'system', label: '模型设置', icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7.5 7.5 0 0 0-2-1.2L14.5 3h-5l-.5 2.6a7.5 7.5 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5a7.4 7.4 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-1a7.5 7.5 0 0 0 2 1.2l.5 2.7h5l.5-2.7a7.5 7.5 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z', comp: markRaw(SystemControl) },
]

const active = ref(new URLSearchParams(window.location.search).has('build_job') || document.querySelector('meta[name="graphrag-build-job"]') ? 'graph' : 'dashboard')
const buildProgress = ref(null)
const ActiveComp = computed(() => navs.find((n) => n.key === active.value).comp)
onMounted(async () => {
  try {
    const current = await api.currentBuild()
    if (current.job_id && current.status === 'running') {
      buildProgress.value = current
      if (active.value === 'dashboard') active.value = 'graph'
    }
  } catch {
    // 旧服务暂未提供任务发现接口，仍由图谱页的恢复信息处理。
  }
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <div class="logo">G</div>
        <div>
          <div class="title">GraphRAG</div>
          <div class="subtitle">知识图谱问答系统</div>
        </div>
      </div>
      <nav>
        <a
          v-for="n in navs"
          :key="n.key"
          :class="{ active: active === n.key }"
          @click="active = n.key"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path :d="n.icon" /></svg>
          <span>{{ n.label }}</span>
        </a>
      </nav>
    </aside>
    <main class="main">
      <button v-if="buildProgress && ['running', 'unknown'].includes(buildProgress.status)" class="btn btn-ghost" style="margin:16px 24px 0" @click="active = 'graph'">
        图谱任务：{{ buildProgress.processed ?? 0 }} / {{ buildProgress.total ?? 0 }} 个分块
        <template v-if="buildProgress.total">（{{ Math.round(buildProgress.processed / buildProgress.total * 100) }}%）</template>
        · {{ buildProgress.status === 'unknown' ? '进度连接中断，点击查看' : '构建中，点击查看' }}
      </button>
      <KeepAlive include="Graph">
        <component :is="ActiveComp" @nav="(k) => (active = k)" @build-progress="buildProgress = $event" />
      </KeepAlive>
    </main>
  </div>
</template>
