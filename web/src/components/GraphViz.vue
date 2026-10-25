<template>
  <div ref="el" class="graph-viz" />
</template>

<script setup>
import * as echarts from 'echarts'
import { onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  links: { type: Array, default: () => [] },
  height: { type: String, default: '520px' },
})

const el = ref(null)
let chart = null
let selectedId = null

const TYPE_CN = {
  PERSON: '人物', ORG: '组织', LOCATION: '地点',
  CONCEPT: '概念', TIME: '时间', EVENT: '事件',
}

const TYPE_COLORS = {
  PERSON: '#5470c6', ORG: '#91cc75', LOCATION: '#fac858',
  CONCEPT: '#ee6666', TIME: '#73c0de', EVENT: '#9a60b4',
}

const RELATION_CN = {
  MEMBER_OF: '隶属', AFFILIATED_WITH: '任职', FOUNDED_BY: '创建',
  CREATED: '提出/发布', LOCATED_IN: '位于', RELATED_TO: '相关',
  CAUSES: '导致', AFFECTS: '影响', PROPOSED_BY: '提出者',
  INVENTED_BY: '发明者', PARTNERS_WITH: '合作', USES: '使用', IN_PERIOD: '时间归属',
}

function render(selected = selectedId) {
  if (!chart) return
  if (!props.nodes.length) {
    selectedId = null
    chart.clear()
    return
  }
  selected = props.nodes.some((n) => n.id === selected) ? selected : null
  selectedId = selected
  const neighborIds = new Set()
  if (selected) {
    for (const l of props.links) {
      if (l.source === selected) neighborIds.add(l.target)
      if (l.target === selected) neighborIds.add(l.source)
    }
  }
  const categoryById = {}
  const nodeData = props.nodes.map((n) => {
    categoryById[n.id] = n.type || 'UNKNOWN'
    return {
      id: n.id,
      name: n.name,
      value: n.mention_count || 0,
      category: n.type || 'UNKNOWN',
      symbolSize: Math.min(80, 12 + (n.mention_count || 1) * 5),
      itemStyle: {
        color: TYPE_COLORS[n.type] || '#999',
        opacity: selected ? (n.id === selected || neighborIds.has(n.id) ? 1 : 0.15) : 1,
      },
      label: { show: true, fontSize: 12, color: '#333' },
      tooltip: {
        formatter: () => {
          const typeCn = TYPE_CN[n.type] || n.type || '未知'
          return `<b>${echarts.format.encodeHTML(n.name)}</b><br/>类型：${echarts.format.encodeHTML(typeCn)}<br/>描述：${echarts.format.encodeHTML(n.description || '（无）')}<br/>出现次数：${echarts.format.encodeHTML(String(n.mention_count || 0))}`
        },
      },
    }
  })
  const linkData = props.links.map((l) => {
    const active = selected ? l.source === selected || l.target === selected || (neighborIds.has(l.source) && neighborIds.has(l.target)) : true
    return {
      id: l.id || JSON.stringify([l.source, l.target, l.relation]),
      source: l.source,
      target: l.target,
      value: l.relation,
      lineStyle: {
        width: Math.min(6, 1 + (l.weight || 1)),
        opacity: selected ? (active ? 0.9 : 0.05) : 0.6,
        color: '#aaa',
        curveness: 0.1,
      },
      label: {
        show: true,
        fontSize: 10,
        color: '#888',
        formatter: RELATION_CN[l.relation] || l.relation,
      },
      tooltip: { formatter: echarts.format.encodeHTML(RELATION_CN[l.relation] || l.relation || '') },
    }
  })
  const categories = [...new Set(Object.values(categoryById))].map((t) => ({
    name: t, itemStyle: { color: TYPE_COLORS[t] || '#999' },
  }))
  chart.setOption(
    {
      tooltip: { trigger: 'item', formatter: (p) => {
        const formatter = p.data?.tooltip?.formatter
        return typeof formatter === 'function' ? formatter() : formatter || ''
      } },
      legend: {
        bottom: 0,
        data: categories.map((c) => c.name),
        formatter: (name) => TYPE_CN[name] || name,
      },
      animationDuration: 500,
      series: [
        {
          id: 'knowledge-graph',
          type: 'graph',
          layout: 'force',
          data: nodeData,
          links: linkData,
          categories,
          roam: true,
          draggable: true,
          force: { repulsion: 220, edgeLength: [60, 160], gravity: 0.1 },
          emphasis: { focus: 'adjacency', label: { fontSize: 14 } },
          lineStyle: { color: 'source' },
        },
      ],
    },
    { notMerge: false, lazyUpdate: true },
  )
}

function onNodeClick(params) {
  if (params.dataType === 'node') {
    render(params.data.id)
  }
}

onMounted(() => {
  chart = echarts.init(el.value)
  chart.on('click', onNodeClick)
  render()
})
onActivated(() => { if (chart) chart.resize() })

onBeforeUnmount(() => {
  if (chart) {
    chart.dispose()
    chart = null
  }
})

watch(() => [props.nodes, props.links], () => render())
watch(() => props.height, (h) => {
  if (el.value) el.value.style.height = h
  if (chart) chart.resize()
})
</script>

<style scoped>
.graph-viz {
  width: 100%;
  height: v-bind(props.height);
  min-height: 300px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}
</style>
