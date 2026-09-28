<script setup>
import { computed, markRaw, ref } from 'vue'
import Documents from './views/Documents.vue'
import Graph from './views/Graph.vue'
import Chat from './views/Chat.vue'

const tabs = [
  { key: 'documents', label: '文档', comp: markRaw(Documents) },
  { key: 'graph', label: '图谱', comp: markRaw(Graph) },
  { key: 'chat', label: '问答', comp: markRaw(Chat) },
]
const active = ref('documents')
const ActiveComp = computed(() => tabs.find((t) => t.key === active.value).comp)
</script>

<template>
  <div class="app">
    <header>
      <h1>知识图谱 RAG 系统</h1>
      <nav>
        <button
          v-for="t in tabs"
          :key="t.key"
          :class="{ active: active === t.key }"
          @click="active = t.key"
        >
          {{ t.label }}
        </button>
        <a class="console-link" href="http://localhost:8001" target="_blank" title="LLM 配置与启停控制">控制台 ⚙</a>
      </nav>
    </header>
    <main>
      <component :is="ActiveComp" />
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f3f4f6; color: #1f2937; }
.app { max-width: 1080px; margin: 0 auto; padding: 20px; }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
header h1 { font-size: 20px; margin: 0; }
nav { display: flex; gap: 8px; }
nav button { border: none; background: #e5e7eb; color: #374151; border-radius: 6px; padding: 8px 18px; cursor: pointer; font-size: 14px; }
nav button.active { background: #2563eb; color: #fff; }
.console-link { color: #2563eb; text-decoration: none; font-size: 14px; border: 1px solid #bfdbfe; background: #eff6ff; border-radius: 6px; padding: 8px 14px; }
main .view { background: #fff; border-radius: 10px; padding: 22px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06); }
h2 { font-size: 18px; margin: 0 0 6px; }
h3 { font-size: 15px; color: #374151; margin: 20px 0 8px; }
</style>
