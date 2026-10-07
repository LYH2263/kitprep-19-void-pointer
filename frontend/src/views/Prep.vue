<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const tree = ref<any[]>([])
const data = ref<any>(null)          // 最新一张【有效】备料单；null = 三处同时为空态
const shortages = ref<any[]>([])
const stats = ref<any>({})
const orders = ref<any[]>([])
const busy = ref(false)
const errorMsg = ref('')

async function refreshShortages() {
  const res = await api('/prep/shortages?order_id=1')
  shortages.value = res.shortages || []
  stats.value = res.stats || {}
}

async function refresh() {
  // 只认有效单：/prep/latest 永不返回作废单，所以页面不可能停在已作废那张上。
  data.value = await api('/prep/latest?order_id=1')
  await refreshShortages()
}

async function run() {
  if (busy.value) return
  // 生成永远是新插一张单，不会写进/覆盖作废单。
  busy.value = true; errorMsg.value = ''
  try {
    data.value = await api('/prep/run?order_id=1', { method: 'POST' })
    await refreshShortages()
  } catch (e) {
    errorMsg.value = '生成失败：' + (e as Error).message
  } finally { busy.value = false }
}

async function voidRun() {
  if (!data.value || busy.value) return
  busy.value = true; errorMsg.value = ''
  try {
    // 后端在同一事务里释放占用并翻转状态；失败会整体退回，前端指针也保持不动。
    const body = await api(`/prep/${data.value.id}/void`, { method: 'POST' })
    // 成功后一次性切到上一张仍有效的单；没有则三处同时变空。
    data.value = body.latest
    shortages.value = body.latest?.shortages || []
    stats.value = body.latest?.stats || {}
  } catch (e) {
    errorMsg.value = '作废失败，单据状态已退回：' + (e as Error).message
  } finally { busy.value = false }
}

onMounted(async () => {
  tree.value = await api('/bom/tree')
  orders.value = await api('/orders')
  await refresh()
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中备料表 · 右缺料便利贴 · 顶栏订单芯片</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <span v-for="o in orders" :key="o.id" class="kp-chip" style="cursor:default">
      {{ o.code }} · {{ o.outlet }}
    </span>
  </div>
  <div class="kp-chips" style="margin-bottom:0.75rem">
    <button class="btn" :disabled="busy" @click="run">生成备料单</button>
    <button class="btn" v-if="data && data.status === 'active'" :disabled="busy"
            style="background:var(--kp-bad,#b33a2b)" @click="voidRun">作废当前单 #{{ data.id }}</button>
    <span v-if="busy" style="font-size:0.8rem;color:#8a8078;align-self:center">处理中…</span>
  </div>
  <p v-if="errorMsg" class="badge badge-bad" style="margin:0 0 0.75rem">{{ errorMsg }}</p>
  <div class="kp-workbench" style="margin-top:0.85rem">
    <aside class="kp-bom-tree">
      <h2>菜品 / BOM</h2>
      <div v-for="d in tree" :key="d.code" class="kp-dish-node">
        <strong>{{ d.dish }}</strong>
        <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
        <ul>
          <li v-for="(c,i) in d.children" :key="i">{{ c.ingredient }} · {{ c.qty }} {{ c.unit }}</li>
        </ul>
      </div>
    </aside>
    <section class="kp-worksheet">
      <template v-if="data">
        <h2>备料单 #{{ data.id }} · {{ data.order?.code }} · {{ data.order?.outlet }}
          <span class="badge badge-ok">有效</span>
          <span style="font-size:0.75rem;color:#8a8078">预占合计 {{ stats.reserved_total_qty ?? 0 }}（仅占用，未出库）</span>
        </h2>
        <table>
          <thead><tr><th>原料</th><th>需求</th><th>库存</th><th>本单占用</th><th>单位</th></tr></thead>
          <tbody>
            <tr v-for="l in data.prep_lines" :key="l.ingredient_id">
              <td>{{ l.ingredient_name }}</td><td>{{ l.need_qty }}</td><td>{{ l.stock_qty }}</td>
              <td>{{ l.reserved_qty ?? 0 }}</td><td>{{ l.unit }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <template v-else>
        <h2>备料单</h2>
        <p class="sub" style="margin:1rem 0">暂无有效备料单（最新一张已作废或从未生成）。点「生成备料单」开始。</p>
      </template>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴</h2>
      <template v-if="data">
        <div v-for="r in shortages" :key="r.ingredient_id" class="kp-shortage-item">
          <span>{{ r.ingredient_name }}</span>
          <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
        </div>
        <p v-if="!shortages.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
      </template>
      <p v-else style="font-size:0.8rem;margin:0.5rem 0 0">无有效备料单，缺料贴为空</p>
    </aside>
  </div>
</template>
