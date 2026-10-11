<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, Position, MarkerType } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { labels } from './api'
interface GraphNode {
  id: number
  level: number
  relative_levels: number[]
  batch_number: string
  item: { name: string; unit: string }
  progress: string
  status: string
}
const props = defineProps<{
  graph: {
    nodes: GraphNode[]
    edges: {
      supplier_order_id: number
      consumer_order_id: number
      quantity: string
      active?: boolean
    }[]
  }
}>()
const nodes = computed(() => {
  const columns: Record<number, number> = {}
  return props.graph.nodes.map((n) => ({
    id: String(n.id),
    position: { x: n.level * 300, y: (columns[n.level] = (columns[n.level] || 0) + 1) * 130 },
    data: {
      label: `${n.item.name}\n${n.batch_number}\n${labels[n.status]} · ${n.progress}%\n冻结 L${n.level} / 当前路径 L${n.relative_levels.join('、')}`,
    },
    sourcePosition: Position.Left,
    targetPosition: Position.Right,
    style: {
      background: n.status === 'COMPLETED' ? '#e6f7ef' : '#fff',
      borderColor: '#a4b7b0',
      width: '250px',
      whiteSpace: 'pre-line' as const,
    },
  }))
})
const edges = computed(() =>
  props.graph.edges.map((e) => ({
    id: `${e.supplier_order_id}-${e.consumer_order_id}`,
    source: String(e.supplier_order_id),
    target: String(e.consumer_order_id),
    label:
      e.quantity +
      ' ' +
      (props.graph.nodes.find((n) => n.id === e.supplier_order_id)?.item.unit || '') +
      (e.active === false ? ' · 已取消关联' : ''),
    animated: e.active !== false,
    style: e.active === false ? { strokeDasharray: '5 5', stroke: '#999' } : undefined,
    markerEnd: MarkerType.ArrowClosed,
  })),
)
</script>
<template>
  <div class="graph-canvas">
    <VueFlow :nodes="nodes" :edges="edges" fit-view-on-init><Background /><Controls /></VueFlow>
  </div>
</template>
<style scoped>
.graph-canvas {
  height: 460px;
  border: 1px solid #e3e9e6;
  border-radius: 12px;
  background: #f7faf8;
}
</style>
