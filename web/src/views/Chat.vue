<template>
  <div class="page">
    <h1 class="page-title">知识问答</h1>
    <p class="page-desc">基于知识图谱的问答：从问题抽取实体 → 图谱扩张 → 生成答案。</p>

    <div class="card chat-card">
      <div ref="scrollBox" class="chat-box">
        <div v-if="!messages.length" class="empty" style="padding:60px 0">
          <p>开始提问，例如：</p>
          <p class="suggestion" @click="useExample('星辰科技是哪一年在哪座城市创办的？')">· 星辰科技是哪一年在哪座城市创办的？</p>
          <p class="suggestion" @click="useExample('李华与清华大学有什么关联？')">· 李华与清华大学有什么关联？</p>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="bubble" :class="m.role">
            <template v-if="m.role === 'user'">{{ m.question }}</template>
            <template v-else>
              <div v-if="m.thinking" class="thinking" role="status">检索与证据核对中…</div>
              <template v-else>
                <CitedAnswer :answer="m.answer" :sentences="m.sentences" :sources="m.sources"
                  :retrieved-sources="m.retrievedSources" :verification="m.verification" />
                <div v-if="m.matched?.length" class="meta">
                  匹配实体：
                  <span v-for="e in m.matched" :key="e" class="chip green">{{ e }}</span>
                </div>
                <div v-if="m.context" class="context-block">
                  <button class="btn btn-ghost btn-sm" @click="m.showCtx = !m.showCtx">
                    {{ m.showCtx ? '收起' : '展开' }}检索上下文（{{ m.nodeCount }} 节点 / {{ m.edgeCount }} 边）
                  </button>
                  <pre v-if="m.showCtx" class="context-text">{{ m.context }}</pre>
                </div>
                <GraphViz v-if="m.subgraph?.nodes?.length && m.showCtx" :nodes="m.subgraph.nodes" :links="m.subgraph.links" height="320px" />
                <div v-if="m.error" class="error-text">{{ m.error }}</div>
              </template>
            </template>
          </div>
        </div>
      </div>

      <div class="input-row">
        <input
          v-model="question"
          aria-label="问题"
          placeholder="输入问题，回车提问"
          @keyup.enter="ask"
          :disabled="asking"
        />
        <button class="btn btn-primary" :disabled="asking || !question.trim()" @click="ask">
          {{ asking ? '思考中' : '提问' }}
        </button>
      </div>
      <div class="params">
        <label>扩展跳数 <select v-model.number="hops"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
        <label>最大节点 <input v-model.number="maxNodes" type="number" min="5" max="200" style="width:70px" /></label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { api } from '../api'
import GraphViz from '../components/GraphViz.vue'
import CitedAnswer from '../components/CitedAnswer.vue'

const question = ref('')
const asking = ref(false)
const hops = ref(2)
const maxNodes = ref(40)
const messages = ref([])
const scrollBox = ref(null)

async function scrollDown() {
  await nextTick()
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
}

function useExample(text) {
  question.value = text
}

async function ask() {
  const q = question.value.trim()
  if (!q || asking.value) return
  asking.value = true
  messages.value.push({ role: 'user', question: q })
  messages.value.push({ role: 'assistant', thinking: true })
  scrollDown()
  const idx = messages.value.length - 1
  try {
    const r = await api.query({ question: q, hops: hops.value, max_nodes: maxNodes.value })
    messages.value[idx] = {
      role: 'assistant',
      answer: r.answer,
      sentences: r.sentences,
      sources: r.sources,
      retrievedSources: r.retrieved_sources,
      verification: r.verification,
      matched: r.matched_entities.map((m) => m.name),
      context: r.context,
      subgraph: r.subgraph,
      nodeCount: r.node_count,
      edgeCount: r.edge_count,
      showCtx: false,
    }
  } catch (e) {
    messages.value[idx] = { role: 'assistant', answer: '', error: e.message, showCtx: false }
  } finally {
    asking.value = false
    question.value = ''
    scrollDown()
  }
}
</script>

<style scoped>
.chat-card { padding: 16px; }
.chat-box { max-height: 58vh; overflow-y: auto; padding: 6px 6px 16px; }
.msg { margin-bottom: 14px; display: flex; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 82%; padding: 11px 15px; border-radius: 14px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; }
.bubble.user { background: var(--primary); color: #fff; border-bottom-right-radius: 4px; }
.bubble.assistant { background: #f8fafc; border: 1px solid var(--border); border-bottom-left-radius: 4px; }
.thinking { color: var(--text-3); }
.answer { color: var(--text); }
.meta { margin-top: 10px; font-size: 13px; color: var(--text-2); }
.context-block { margin-top: 10px; }
.context-text { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 12px; line-height: 1.6; max-height: 260px; overflow-y: auto; white-space: pre-wrap; margin: 8px 0 0; }
.suggestion { color: var(--primary); cursor: pointer; margin: 4px 0; }
.input-row { display: flex; gap: 10px; margin-top: 8px; }
.input-row input { flex: 1; padding: 11px 14px; border: 1px solid var(--border); border-radius: 10px; font-size: 14px; outline: none; }
.input-row input:focus { border-color: var(--primary); }
.params { display: flex; gap: 18px; margin-top: 10px; color: var(--text-2); font-size: 13px; align-items: center; }
.params select, .params input { border: 1px solid var(--border); border-radius: 6px; padding: 4px 6px; }
</style>
