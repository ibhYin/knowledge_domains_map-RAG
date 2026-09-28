<template>
  <div class="page">
    <h1 class="page-title">文档管理</h1>
    <p class="page-desc">上传 PDF / MD / TXT / DOCX，系统会自动分块，供后续构建知识图谱。</p>

    <div class="card">
      <div
        class="dropzone"
        :class="{ dragging }"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
        @click="fileInput?.click()"
      >
        <input ref="fileInput" type="file" multiple accept=".pdf,.md,.txt,.docx" hidden @change="onFiles" />
        <div class="dz-icon">
          <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
        </div>
        <p class="dz-title">点击或拖拽文件到此处上传</p>
        <p class="muted">支持 PDF / MD / TXT / DOCX，可多选</p>
      </div>
      <div v-if="uploading" class="progress-track"><div class="progress-bar" style="width: 100%"></div></div>
      <div class="msg" :class="uploadError ? 'err' : 'ok'" v-if="uploadMsg">{{ uploadMsg }}</div>
    </div>

    <div class="card">
      <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>已上传文档（{{ docs.length }}）</span>
        <button class="btn btn-ghost btn-sm" @click="refresh">刷新</button>
      </div>
      <table v-if="docs.length" class="data-table">
        <thead>
          <tr><th>文件名</th><th>分块数</th><th>上传时间</th><th style="width:80px">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in docs" :key="d.doc_id">
            <td>{{ d.filename }}</td>
            <td><span class="chip">{{ d.chunk_count }}</span></td>
            <td class="muted">{{ d.uploaded_at }}</td>
            <td><button class="btn btn-ghost btn-sm" style="color:var(--danger)" @click="removeDoc(d.doc_id)">删除</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">暂无文档。上传后到「图谱」页构建知识图谱。</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const docs = ref([])
const uploading = ref(false)
const dragging = ref(false)
const uploadMsg = ref('')
const uploadError = ref(false)
const fileInput = ref(null)

async function refresh() {
  try {
    const data = await api.listDocuments()
    docs.value = data.documents
  } catch (e) {
    uploadMsg.value = '获取文档列表失败：' + e.message
    uploadError.value = true
  }
}

async function handleFiles(files) {
  if (!files.length) return
  uploading.value = true
  uploadMsg.value = ''
  try {
    const data = await api.uploadDocuments(files)
    uploadError.value = false
    uploadMsg.value = data.ingested.map((r) => `${r.filename} → ${r.chunk_count} 块`).join('；')
    await refresh()
  } catch (e) {
    uploadError.value = true
    uploadMsg.value = '上传失败：' + e.message
  } finally {
    uploading.value = false
  }
}

function onFiles(e) {
  handleFiles(Array.from(e.target.files || []))
  e.target.value = ''
}
function onDrop(e) {
  dragging.value = false
  handleFiles(Array.from(e.dataTransfer.files || []))
}

async function removeDoc(docId) {
  if (!confirm('确定删除该文档及其分块？')) return
  try {
    await api.deleteDocument(docId)
    await refresh()
  } catch (e) {
    alert('删除失败：' + e.message)
  }
}

onMounted(refresh)
</script>

<style scoped>
.dropzone {
  border: 2px dashed var(--border); border-radius: var(--radius);
  padding: 34px 20px; text-align: center; cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.dropzone:hover, .dropzone.dragging { border-color: var(--primary); background: var(--primary-50); }
.dz-icon { color: var(--primary); margin-bottom: 8px; }
.dz-title { font-size: 14px; margin: 0 0 2px; }
</style>
