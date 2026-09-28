<template>
  <div class="view">
    <h2>文档管理</h2>
    <div class="upload-box">
      <input
        type="file"
        multiple
        accept=".pdf,.md,.txt,.docx"
        @change="onFileChange"
      />
      <span class="hint">支持 PDF / MD / TXT / DOCX</span>
    </div>
    <div v-if="uploading" class="status">上传与分块中…</div>
    <div v-if="uploadResult" class="success">
      {{ uploadResult.map((r) => `${r.filename} → ${r.chunk_count} 块`).join('；') }}
    </div>

    <h3>已上传文档（{{ docs.length }}）</h3>
    <table class="doc-table">
      <thead>
        <tr><th>文件名</th><th>分块数</th><th>上传时间</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="d in docs" :key="d.doc_id">
          <td>{{ d.filename }}</td>
          <td>{{ d.chunk_count }}</td>
          <td>{{ d.uploaded_at }}</td>
          <td><button class="danger" @click="removeDoc(d.doc_id)">删除</button></td>
        </tr>
      </tbody>
    </table>
    <p v-if="!docs.length" class="empty">暂无文档，请先上传。</p>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const docs = ref([])
const uploading = ref(false)
const uploadResult = ref(null)

async function refresh() {
  const data = await api.listDocuments()
  docs.value = data.documents
}

async function onFileChange(e) {
  const files = Array.from(e.target.files || [])
  if (!files.length) return
  uploading.value = true
  uploadResult.value = null
  try {
    const data = await api.uploadDocuments(files)
    uploadResult.value = data.ingested
    await refresh()
  } catch (err) {
    alert(`上传失败：${err.message}`)
  } finally {
    uploading.value = false
    e.target.value = ''
  }
}

async function removeDoc(docId) {
  if (!confirm('确定删除该文档及其分块？')) return
  try {
    await api.deleteDocument(docId)
    await refresh()
  } catch (err) {
    alert(`删除失败：${err.message}`)
  }
}

onMounted(refresh)
</script>

<style scoped>
.upload-box { display: flex; align-items: center; gap: 12px; margin: 12px 0; }
.hint { color: #888; font-size: 13px; }
.success { color: #16a34a; margin: 8px 0; }
.status { color: #2563eb; margin: 8px 0; }
.doc-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.doc-table th, .doc-table td { border: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; }
.doc-table th { background: #f9fafb; }
.danger { color: #dc2626; border: 1px solid #fca5a5; background: #fff; border-radius: 4px; padding: 4px 10px; cursor: pointer; }
.empty { color: #999; }
</style>
