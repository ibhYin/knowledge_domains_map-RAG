<template>
  <div class="view">
    <h2>知识问答</h2>
    <div class="chat-box">
      <div class="msg" :class="m.role" v-for="(m, i) in messages" :key="i">
        <div class="bubble">
          <div v-if="m.role === 'user'">{{ m.question }}</div>
          <template v-else>
            <div class="answer">{{ m.answer }}</div>
            <div v-if="m.matched && m.matched.length" class="meta">
              匹配实体：<span v-for="e in m.matched" :key="e.node" class="chip">{{ e.name }}</span>
            </div>
            <div v-if="m.context" class="context-block">
              <button @click="m.showCtx = !m.showCtx">检索上下文（{{ m.nodeCount }} 节点 / {{ m.edgeCount }} 边）</button>
              <pre v-if="m.showCtx" class="context-text">{{ m.context }}</pre>
            </div>
            <GraphViz v-if="m.subgraph && m.subgraph.nodes.length" :nodes="m.subgraph.nodes" :links="m.subgraph.links" height="380px" />
            <div v-if="m.error" class="error-text">{{ m.error }}</div>
          </template>
        </div>
      </div>
    </div>
    <div class="input-row">
      <input
        v-model="question"
        placeholder="输入问题，例如：星辰科技与清华大学有什么关联？"
        @keyup.enter="ask"
        :disabled="asking"
      />
      <button :disabled="asking || !question.trim()" @click="ask">
        {{ asking ? '思考中…' : '提问' }}
      </button>
    </div>
    <div class="params">
      <label>跳数 <select v-model.number="hops"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
      <label>最大节点 <input v-model.number="maxNodes" type="number" min="5" max="200" /></label>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api'
import GraphViz from '../components/GraphViz.vue'

const question = ref('')
const asking = ref(false)
const hops = ref(2)
const maxNodes = ref(40)
const messages = ref([])

async function ask() {
  const q = question.value.trim()
  if (!q || asking.value) return
  asking.value = true
  messages.value.push({ role: 'user', question: q })
  const idx = messages.value.length
  messages.value.push({ role: 'assistant', answer: '…', showCtx: false })
  try {
    const r = await api.query({ question: q, hops: hops.value, max_nodes: maxNodes.value })
    messages.value[idx] = {
      role: 'assistant',
      answer: r.answer,
      matched: r.matched_entities,
      context: r.context,
      subgraph: r.subgraph,
      nodeCount: r.node_count,
      edgeCount: r.edge_count,
      showCtx: false,
    }
  } catch (err) {
    messages.value[idx] = { role: 'assistant', answer: '', error: err.message, showCtx: false }
  } finally {
    asking.value = false
    question.value = ''
  }
}
</script>

<style scoped>
.chat-box { max-height: 62vh; overflow-y: auto; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; background: #fafafa; }
.msg { margin-bottom: 12px; }
.msg.user { text-align: right; }
.bubble { display: inline-block; max-width: 90%; text-align: left; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 14px; white-space: pre-wrap; }
.msg.user .bubble { background: #2563eb; color: #fff; border-color: #2563eb; }
.answer { line-height: 1.7; }
.meta { margin-top: 10px; color: #6b7280; font-size: 13px; }
.chip { display: inline-block; background: #eff6ff; color: #1d4ed8; border-radius: 999px; padding: 2px 10px; margin: 2px; font-size: 12px; }
.context-block { margin-top: 8px; }
.context-block button { background: #f3f4f6; color: #374151; border: 1px solid #d1d5db; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
.context-text { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px; font-size: 12px; line-height: 1.6; max-height: 240px; overflow-y: auto; white-space: pre-wrap; }
.error-text { color: #dc2626; }
.input-row { display: flex; gap: 8px; margin-top: 12px; }
.input-row input { flex: 1; padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; }
.input-row button { background: #2563eb; color: #fff; border: none; border-radius: 6px; padding: 0 20px; cursor: pointer; }
.input-row button:disabled { opacity: 0.6; }
.params { margin-top: 8px; display: flex; gap: 16px; color: #6b7280; font-size: 13px; }
.params input, .params select { width: 60px; padding: 4px; border: 1px solid #d1d5db; border-radius: 4px; }
</style>
