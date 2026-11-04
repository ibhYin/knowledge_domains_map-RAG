// Run: node --experimental-vm-modules docs/check_cited_answer.mjs
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import vm from 'node:vm'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const vue = require('vue')
const { renderToString } = require('vue/server-renderer')
const { parse, compileScript } = require('@vue/compiler-sfc')
const source = await readFile(new URL('../web/src/components/CitedAnswer.vue', import.meta.url), 'utf8')
const code = compileScript(parse(source).descriptor, { id: 'citation-check', inlineTemplate: true }).content
const context = vm.createContext({})
const module = new vm.SourceTextModule(code, { context })
await module.link(name => {
  assert.equal(name, 'vue')
  return new vm.SyntheticModule(Object.keys(vue), function () {
    for (const [key, value] of Object.entries(vue)) this.setExport(key, value)
  }, { context })
})
await module.evaluate()
const component = module.namespace.default
const html = await renderToString(vue.createSSRApp(component, {
  sentences: [{ text: '已核对的句子。', citations: [{ source_id: 1 }, { source_id: 1 }] }],
  sources: [{ id: 1, filename: '<script>bad</script>.txt', chunk_index: 0, page: 2,
    deleted: true, content: '<img src=x onerror=bad()>', quotes: ['证据片段'] }],
  retrievedSources: [{ id: 2, filename: '未引用.txt', chunk_index: 1, content: '其他原文' }],
  verification: 'partial',
}))
assert.equal((html.match(/aria-label="查看来源 1"/g) || []).length, 1)
assert.ok(html.includes('原文已删除') && html.includes('证据快照'))
assert.ok(html.includes('检索到但未引用') && html.includes('证据片段'))
assert.ok(html.includes('第 2 页') && html.includes('分块 1'))
assert.ok(html.includes('&lt;script&gt;') && html.includes('&lt;img'))
assert.ok(!html.includes('<script>bad') && !html.includes('<img src=x'))
const legacy = await renderToString(vue.createSSRApp(component, { answer: '旧版历史答案' }))
assert.ok(legacy.includes('旧版历史答案'))
console.log('PASS: citation buttons, source snapshots, unused sources, safe text and legacy history')
