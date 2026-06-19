export const LARGE_GRAPH_NODE_THRESHOLD = 500
export const LARGE_GRAPH_EDGE_THRESHOLD = 1500
export const MAX_RENDER_NODES = 650
export const MAX_RENDER_EDGES = 1400

export function getGraphCounts(graphData) {
  return {
    nodeCount: graphData?.node_count ?? graphData?.nodes?.length ?? 0,
    edgeCount: graphData?.edge_count ?? graphData?.edges?.length ?? 0,
  }
}

export function isLargeGraphData(graphData) {
  const { nodeCount, edgeCount } = getGraphCounts(graphData)
  return nodeCount > LARGE_GRAPH_NODE_THRESHOLD || edgeCount > LARGE_GRAPH_EDGE_THRESHOLD
}

export function canRenderEdgeLabels({ sampled }) {
  return !sampled
}

export function shouldRenderEdgeLabels({ showEdgeLabels, sampled }) {
  return Boolean(showEdgeLabels) && canRenderEdgeLabels({ sampled })
}
