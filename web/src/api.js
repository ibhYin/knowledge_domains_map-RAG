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
  listDocuments: () => request('/api/documents'),
  uploadDocuments: (files) => {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    return request('/api/documents/ingest', { method: 'POST', body: form })
  },
  deleteDocument: (docId) => request(`/api/documents/${docId}`, { method: 'DELETE' }),
  buildGraph: (docIds = null) => postJSON('/api/graph/build', { doc_ids: docIds }),
  buildStatus: (jobId) => request(`/api/graph/build/status/${jobId}`),
  graphStats: () => request('/api/graph/stats'),
  graphViz: () => request('/api/graph/viz'),
  clearGraph: () => postJSON('/api/graph/clear', {}),
  query: (payload) => postJSON('/api/query', payload),
}
