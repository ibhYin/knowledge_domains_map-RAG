async function request(path, options = {}) {
  const resp = await fetch(path, options)
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const data = await resp.json()
      detail = data.detail || JSON.stringify(data)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json()
}

function postJSON(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  health: () => request('/api/health'),
  overview: () => request('/api/overview'),

  // 文档
  listDocuments: () => request('/api/documents'),
  uploadDocuments: (files) => {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    return request('/api/documents/ingest', { method: 'POST', body: form })
  },
  deleteDocument: (docId) => request(`/api/documents/${docId}`, { method: 'DELETE' }),

  // 图谱
  buildGraph: (docIds = null) => postJSON('/api/graph/build', { doc_ids: docIds }),
  buildStatus: (jobId) => request(`/api/graph/build/status/${jobId}`),
  graphStats: () => request('/api/graph/stats'),
  graphViz: () => request('/api/graph/viz'),
  clearGraph: () => postJSON('/api/graph/clear', {}),

  // 图谱浏览器
  entitySearch: (q, limit = 20) => request(`/api/entities/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  entityDetail: (key) => request(`/api/entities/${encodeURIComponent(key)}`),
  findPath: (from, to) => request(`/api/path?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),

  // 问答与历史
  query: (payload) => postJSON('/api/query', payload),
  history: () => request('/api/history'),
  clearHistory: () => request('/api/history', { method: 'DELETE' }),

  // 设置与系统控制
  settings: () => request('/api/settings'),
  saveSettings: (payload) => postJSON('/api/settings', payload),
  controlStatus: () => request('/api/control/status'),
  controlLogs: (n = 100) => request(`/api/control/logs?n=${n}`),
  controlStart: () => postJSON('/api/control/start', {}),
  controlStop: () => postJSON('/api/control/stop', {}),
  controlRestart: () => postJSON('/api/control/restart', {}),
}
