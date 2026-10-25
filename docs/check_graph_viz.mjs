// Run: node --experimental-vm-modules docs/check_graph_viz.mjs
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import vm from 'node:vm'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const { parse, compileScript } = require('@vue/compiler-sfc')
const vue = require('vue')
const { format } = require('echarts')
const source = await readFile(new URL('../web/src/components/GraphViz.vue', import.meta.url), 'utf8')
const compiled = compileScript(parse(source).descriptor, { id: 'viz-check' }).content
const hooks = {}
const calls = []
let click, cleared = 0, resized = 0, disposed = 0
const chart = {
  setOption: (...args) => calls.push(args),
  on: (name, handler) => { assert.equal(name, 'click'); click = handler },
  clear: () => { cleared++ }, resize: () => { resized++ }, dispose: () => { disposed++ },
}
const context = vm.createContext({})
const dependencies = {
  vue: { ref: vue.ref, watch: vue.watch, unref: vue.unref, useCssVars() {}, onMounted: fn => { hooks.mount = fn },
    onBeforeUnmount: fn => { hooks.unmount = fn }, onActivated: fn => { hooks.activate = fn } },
  echarts: { init: () => chart, format },
}
const module = new vm.SourceTextModule(compiled, { context })
await module.link(specifier => {
  const exports = dependencies[specifier]
  return new vm.SyntheticModule(Object.keys(exports), function () {
    for (const [name, value] of Object.entries(exports)) this.setExport(name, value)
  }, { context })
})
await module.evaluate()
const props = vue.reactive({
  height: '520px',
  nodes: [{ id: 'a', name: '<img src=x onerror=alert(1)>', type: 'ORG' },
          { id: 'b', name: '乙', type: 'ORG' }, { id: 'c', name: '丙', type: 'ORG' }],
  links: [{ source: 'a', target: 'b', relation: 'USES' },
          { source: 'a', target: 'b', relation: 'PARTNERS_WITH' }],
})
module.namespace.default.setup(props, { expose() {} })
hooks.mount()
const first = calls.at(-1)[0]
assert.equal(calls.at(-1)[1].notMerge, false)
assert.equal(first.series[0].id, 'knowledge-graph')
assert.notEqual(first.series[0].links[0].id, first.series[0].links[1].id)
assert.ok(first.tooltip.formatter({ data: first.series[0].data[0] }).includes('&lt;img'))
assert.equal(first.tooltip.formatter({ data: first.series[0].links[0] }), '使用')

click({ dataType: 'node', data: { id: 'a' } })
props.nodes = [...props.nodes, { id: 'd', name: '新增实体', type: 'ORG' }]
await vue.nextTick()
const updated = calls.at(-1)[0]
assert.equal(updated.series[0].data.length, 4)
assert.equal(updated.series[0].id, first.series[0].id)
assert.equal(updated.series[0].links[0].id, first.series[0].links[0].id)
assert.equal(updated.series[0].data.find(n => n.id === 'a').itemStyle.opacity, 1)
assert.equal(updated.series[0].data.find(n => n.id === 'd').itemStyle.opacity, 0.15)
assert.equal(calls.at(-1)[1].notMerge, false)
props.nodes = []
props.links = []
await vue.nextTick()
assert.equal(cleared, 1)
hooks.activate()
assert.equal(resized, 1)
hooks.unmount()
assert.equal(disposed, 1)
console.log('PASS: stable series/edge IDs, merged updates, retained selection, safe tooltips, empty/resize/dispose lifecycle')
