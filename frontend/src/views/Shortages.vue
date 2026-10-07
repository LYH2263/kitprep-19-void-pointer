<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const stats = ref<any>({})
const runId = ref<number | null>(null)
onMounted(async () => {
  // 统计只跟最新【有效】单；最新一张作废后这里自动变空，不会停在作废单数字上。
  const res = await api('/prep/shortages?order_id=1')
  rows.value = res.shortages; stats.value = res.stats || {}; runId.value = res.run_id
})
</script>
<template>
  <h1>缺料便利贴</h1>
  <p class="sub">shortage = need − stock（仅正数）</p>
  <template v-if="runId">
    <p class="sub" style="margin-bottom:0.5rem">数据来自有效备料单 #{{ runId }}</p>
    <div class="kp-shortage-sticky" style="max-width:360px;transform:rotate(-1deg);margin-bottom:1rem">
      <h2>⚠ 缺料 {{ stats.shortage_count }} · 合计 {{ stats.total_shortage_qty }}</h2>
      <div v-for="r in rows" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>原料</th><th>需求</th><th>库存</th><th>缺料</th><th>单位</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.ingredient_id">
            <td>{{ r.ingredient_name }}</td><td>{{ r.need_qty }}</td><td>{{ r.stock_qty }}</td>
            <td><span class="badge badge-bad">{{ r.shortage }}</span></td><td>{{ r.unit }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
  <div v-else class="card" style="max-width:420px">
    <h2>暂无有效备料单</h2>
    <p class="sub" style="margin:0.5rem 0 0">最新备料单已作废或尚未生成，缺料贴与统计均为空。请到「备料单」生成新单。</p>
  </div>
</template>
