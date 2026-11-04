// Run: node --experimental-vm-modules docs/check_build_task.mjs
// Compile the real SFC, exercise its async logic with fake API/storage/timers.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import vm from 'node:vm'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const { parse, compileScript } = require('@vue/compiler-sfc')
const vue = require('vue')
const source = await readFile(new URL('../web/src/views/Graph.vue', import.meta.url), 'utf8')
const compiled = compileScript(parse(source).descriptor, { id: 'task-check' }).content
const key = 'graphrag.buildJobId'
const id = 'abcdef123456'
let starts = 0
let state = { status: 'running', processed: 7, total: 20, failed: 0 }
let failure = null
let discoveryFailure = null
let currentId = null
let snapshot = null
let vizCalls = 0
const api = {
  currentBuild: async () => { if (discoveryFailure) throw discoveryFailure; return { job_id: currentId } },
  buildGraph: async () => { starts++; return { job_id: id } },
  buildStatus: async () => { if (failure) throw failure; return { ...state } },
  graphStats: async () => ({ nodes: 0, edges: 0 }),
  graphViz: async () => { vizCalls++; return snapshot || { nodes: [], links: [] } },
  clearGraph: async () => ({}),
}

async function mount(storage = new Map(), href = 'http://localhost:8002/', bootstrap = null) {
  const hooks = {}
  const timers = new Map()
  const window = { location: { href }, history: { replaceState: (_a, _b, url) => { window.location.href = String(url) } } }
  const context = vm.createContext({
    URL, window, document: { querySelector: () => bootstrap ? { content: bootstrap } : null }, confirm: () => true,
    localStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
    setTimeout: callback => { const timer = Symbol(); timers.set(timer, callback); return timer },
    clearTimeout: timer => timers.delete(timer),
  })
  const dependencies = {
    vue: { computed: vue.computed, ref: vue.ref, watch: vue.watch,
      onMounted: fn => { hooks.mount = fn }, onBeforeUnmount: fn => { hooks.unmount = fn },
      onActivated: fn => { hooks.activate = fn }, onDeactivated: fn => { hooks.deactivate = fn } },
    '../api': { api },
    '../components/GraphViz.vue': { default: {} },
  }
  const module = new vm.SourceTextModule(compiled, { context })
  await module.link(specifier => {
    const exports = dependencies[specifier]
    assert.ok(exports, specifier)
    return new vm.SyntheticModule(Object.keys(exports), function () {
      for (const [name, value] of Object.entries(exports)) this.setExport(name, value)
    }, { context })
  })
  await module.evaluate()
  const events = []
  const component = module.namespace.default.setup({}, { expose() {}, emit: (...event) => events.push(event) })
  await hooks.mount()
  return { component, hooks, timers, storage, window, events }
}

const first = await mount()
await first.component.startBuild()
assert.equal(starts, 1)
assert.equal(first.storage.get(key), id)
assert.equal(first.component.building.value, true)
await first.component.startBuild()
assert.equal(starts, 1, 'Do not submit another build while one is tracked')
first.hooks.unmount()
assert.equal(first.timers.size, 0)

const restored = await mount(first.storage)
assert.equal(restored.component.job.value.processed, 7)
assert.equal(starts, 1, 'Restore by GET, never by submitting a build')
restored.hooks.unmount()

currentId = id
const discovered = await mount()
assert.equal(discovered.component.job.value.processed, 7)
assert.equal(discovered.storage.get(key), id)
assert.equal(discovered.events.at(-1)[0], 'build-progress')
assert.equal(starts, 1, 'Discover the server task without resubmission or browser storage')
discovered.hooks.unmount()
currentId = null

discoveryFailure = Object.assign(new Error('old server'), { status: 404 })
const bootstrapped = await mount(new Map(), 'http://localhost:8002/', id)
assert.equal(bootstrapped.component.job.value.processed, 7)
assert.equal(bootstrapped.storage.get(key), id)
bootstrapped.hooks.unmount()
discoveryFailure = null

const linked = await mount(new Map(), `http://localhost:8002/?build_job=${id}`)
assert.equal(linked.storage.get(key), id)
assert.equal(new URL(linked.window.location.href).searchParams.has('build_job'), false)
linked.hooks.unmount()

failure = Object.assign(new Error('offline'), { status: 503 })
const disconnected = await mount(first.storage)
assert.equal(disconnected.component.job.value.status, 'unknown')
assert.equal(disconnected.component.building.value, true)
assert.equal(first.storage.get(key), id)
failure = null
await disconnected.component.poll(id)
assert.equal(disconnected.component.job.value.status, 'running')
assert.equal(disconnected.timers.size, 1)
disconnected.hooks.unmount()

failure = Object.assign(new Error('missing'), { status: 404 })
const missing = await mount(new Map([[key, id]]))
assert.equal(missing.component.job.value.status, 'missing')
assert.equal(missing.component.building.value, false)
assert.equal(missing.storage.has(key), false)
failure = null

state = { status: 'partial', processed: 20, total: 20, failed: 2 }
const completed = await mount(new Map([[key, id]]))
assert.equal(completed.component.job.value.status, 'partial')
assert.equal(completed.component.building.value, false)
assert.equal(completed.timers.size, 0)
await completed.component.clearGraph()
assert.equal(completed.storage.has(key), false)
assert.equal(completed.component.job.value, null)
assert.equal(starts, 1)
function graph(version, count = version) {
  const nodes = Array.from({ length: count }, (_, i) => ({ id: `n${i}`, name: `实体${i}` }))
  const links = nodes.slice(1).map((n, i) => ({ source: `n${i}`, target: n.id, relation: 'USES' }))
  return { graph_version: version, nodes, links, stats: { graph_version: version, nodes: count, edges: links.length } }
}
currentId = id
state = { status: 'running', processed: 1, total: 20, failed: 0, graph_version: 1 }
snapshot = graph(1)
const growing = await mount()
assert.equal(growing.component.viz.value.nodes.length, 1)
const calls = vizCalls
await growing.component.poll(id)
assert.equal(vizCalls, calls, 'Do not refetch a graph whose published version has not changed')
state = { ...state, processed: 2, graph_version: 2 }
snapshot = graph(2)
await growing.component.poll(id)
assert.equal(growing.component.viz.value.nodes.length, 2)
assert.equal(growing.component.stats.value.nodes, 2)
assert.equal(growing.component.publishedVersion.value, 2)
growing.hooks.deactivate()
state = { ...state, processed: 3, graph_version: 3 }
snapshot = graph(3)
const hiddenCalls = vizCalls
await growing.component.poll(id)
assert.equal(vizCalls, hiddenCalls, 'Keep progress polling while avoiding hidden graph rendering')
await growing.hooks.activate()
assert.equal(growing.component.viz.value.nodes.length, 3)

const graphApi = api.graphViz
let deliverOld
api.graphViz = () => new Promise(resolve => { deliverOld = resolve })
const olderRequest = growing.component.refresh()
api.graphViz = async () => graph(5)
await growing.component.refresh()
deliverOld(graph(4))
await olderRequest
assert.equal(growing.component.publishedVersion.value, 5, 'Late responses must not overwrite a newer graph')
api.graphViz = async () => { throw new Error('snapshot unavailable') }
await growing.component.refresh()
assert.equal(growing.component.viz.value.nodes.length, 5)
assert.equal(growing.component.graphError.value, 'snapshot unavailable')
api.graphViz = async () => graph(6, 400)
await growing.component.refresh()
assert.equal(growing.component.viz.value.nodes.length, 300)
assert.equal(growing.component.stats.value.nodes, 400)
assert.equal(growing.component.viz.value.truncated, true)
assert.equal(growing.component.graphError.value, '')
api.graphViz = graphApi
growing.hooks.unmount()
assert.equal(growing.timers.size, 0)
console.log('PASS: task recovery, published-version growth, consistent counts, hidden-view gating, stale/error retention and preview bounds')
