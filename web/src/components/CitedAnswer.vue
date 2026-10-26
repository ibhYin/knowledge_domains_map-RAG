<template>
  <div class="cited-answer">
    <template v-if="sentences.length">
      <p v-for="(sentence, index) in sentences" :key="index" class="sentence">
        {{ sentence.text }}
        <button v-for="id in sourceIds(sentence)" :key="id" class="citation"
          :aria-label="`查看来源 ${id}`" @click="showSource(id)">[{{ id }}]</button>
      </p>
    </template>
    <div v-else class="plain-answer">{{ answer }}</div>
    <p v-if="verification === 'verified'" class="verification">已完成原文与逐句证据核对</p>
    <p v-else-if="verification === 'partial'" class="verification">已移除未通过证据核对的内容，以下仅展示保留句子的引用。</p>
    <div v-if="sources.length" class="sources">
      <p class="source-title">实际引用（{{ sources.length }}）</p>
      <details v-for="source in sources" :key="source.id" :ref="el => { panels[source.id] = el }">
        <summary>[{{ source.id }}] {{ source.filename }} · 分块 {{ source.chunk_index + 1 }}<template v-if="source.page"> · 第 {{ source.page }} 页</template><span v-if="source.deleted" class="deleted"> · 原文已删除</span></summary>
        <p v-if="source.deleted" class="verification">以下为回答时保存的证据快照。</p>
        <blockquote v-for="quote in source.quotes" :key="quote">{{ quote }}</blockquote>
        <details class="original"><summary>查看完整原文分块</summary><pre>{{ source.content }}</pre></details>
      </details>
    </div>
    <details v-if="retrievedSources.length" class="retrieved">
      <summary>检索到但未引用（{{ retrievedSources.length }}）</summary>
      <details v-for="source in retrievedSources" :key="source.id">
        <summary>[{{ source.id }}] {{ source.filename }} · 分块 {{ source.chunk_index + 1 }}<span v-if="source.deleted" class="deleted"> · 原文已删除</span></summary>
        <pre>{{ source.content }}</pre>
      </details>
    </details>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  answer: { type: String, default: '' },
  sentences: { type: Array, default: () => [] },
  sources: { type: Array, default: () => [] },
  retrievedSources: { type: Array, default: () => [] },
  verification: { type: String, default: '' },
})
const panels = ref({})
const sourceIds = sentence => [...new Set(sentence.citations.map(c => c.source_id))]
function showSource(id) {
  const panel = panels.value[id]
  if (!panel) return
  panel.open = true
  panel.querySelector('summary')?.focus()
}
</script>

<style scoped>
.cited-answer { white-space: normal; overflow-wrap: anywhere; }
.sentence { margin: 0 0 8px; }
.plain-answer, blockquote, pre { white-space: pre-wrap; }
.citation { border: 0; background: var(--primary-50); color: var(--primary); border-radius: 4px; padding: 2px 5px; margin-left: 4px; cursor: pointer; font: inherit; }
.citation:focus-visible, summary:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; }
.verification { font-size: 12px; color: var(--text-2); margin: 8px 0; }
.source-title { font-weight: 600; margin: 12px 0 6px; }
details { margin: 6px 0; border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: var(--surface); }
summary { cursor: pointer; font-size: 12.5px; }
blockquote { margin: 8px 0; padding: 4px 10px; border-left: 3px solid var(--primary); color: var(--text-2); }
pre { font: inherit; font-size: 12px; max-height: 260px; overflow-y: auto; }
.deleted { color: var(--danger); }
.retrieved { margin-top: 12px; }
</style>
