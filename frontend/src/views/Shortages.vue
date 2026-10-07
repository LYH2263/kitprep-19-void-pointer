<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const stats = ref<any>({ ingredient_count: 0, shortage_count: 0, total_shortage_qty: 0 })
const runId = ref<number | null>(null)
onMounted(async () => {
  // 只取最新有效单；若最新单已作废且无更早有效单，后端返回空缺料与归零统计。
  const res = await api('/prep/shortages?order_id=1')
  runId.value = res.run_id
  rows.value = res.shortages
  stats.value = res.stats
})
</script>
<template>
  <h1>缺料便利贴</h1>
  <p class="sub">shortage = need − 可用量（账面结存 − 已预占），仅正数</p>
  <div v-if="runId == null" class="card kp-empty-page">
    <strong>暂无有效备料单</strong>
    <p class="muted" style="margin:0.35rem 0 0">最新备料单已作废或缺料随之为空，请到「备料单」生成新单。</p>
  </div>
  <template v-else>
    <div class="kp-shortage-sticky" style="max-width:360px;transform:rotate(-1deg);margin-bottom:1rem">
      <h2>备料单 #{{ runId }} · 缺料 {{ stats.shortage_count }} · 合计 {{ stats.total_shortage_qty }}</h2>
      <div v-for="r in rows" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!rows.length" style="font-size:0.8rem;margin:0.4rem 0 0">暂无缺料</p>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>原料</th><th>需求</th><th>可用</th><th>缺料</th><th>单位</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.ingredient_id">
            <td>{{ r.ingredient_name }}</td><td>{{ r.need_qty }}</td><td>{{ r.available_qty }}</td>
            <td><span class="badge badge-bad">{{ r.shortage }}</span></td><td>{{ r.unit }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
