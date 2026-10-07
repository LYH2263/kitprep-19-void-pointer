<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const tree = ref<any[]>([])
const data = ref<any>(null)          // 始终是"最新有效单"；作废成功后由后端返回的新指针替换，或置空
const orders = ref<any[]>([])
const busy = ref(false)
const errorMsg = ref('')

// 缺料贴与中间备料表共用同一个 data 指针，杜绝两处停在不同单据上。
const shortages = computed<any[]>(() => data.value?.shortages || [])

async function loadLatest() {
  // 只读取最新有效单；没有有效单时后端返回 null，不再借 GET 隐式建单。
  data.value = await api('/prep/latest?order_id=1')
}

async function run() {
  busy.value = true; errorMsg.value = ''
  try {
    // 永远新建一张单，绝不写入或覆盖已作废单。
    data.value = await api('/prep/run?order_id=1', { method: 'POST' })
  } catch (e: any) {
    errorMsg.value = '生成失败：' + e.message
  } finally {
    busy.value = false
  }
}

async function voidCurrent() {
  if (!data.value) return
  if (!window.confirm(`确认作废备料单 #${data.value.id}？\n作废不做出库，仅释放本单预占，且不可恢复。`)) return
  busy.value = true; errorMsg.value = ''
  try {
    const res = await api(`/prep/${data.value.id}/void`, { method: 'POST' })
    // 成功后三处统一切到后端给出的新指针：上一张有效单，或同时变空。
    data.value = res.latest
  } catch (e: any) {
    // 失败：后端已回滚，指针与单据状态都没变；重新拉取以与服务端对齐。
    errorMsg.value = '作废失败，单据与占用均未改动：' + e.message
    await loadLatest()
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  tree.value = await api('/bom/tree')
  orders.value = await api('/orders')
  await loadLatest()
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
  <div class="kp-actions">
    <button class="btn" :disabled="busy" @click="run">生成备料单</button>
    <button class="btn btn-danger" :disabled="busy || !data" @click="voidCurrent">作废当前备料单</button>
    <span v-if="data" class="kp-run-tag">
      当前 #{{ data.id }} · {{ data.order?.code }} · {{ data.order?.outlet }}
      <span class="badge badge-ok">有效</span>
    </span>
    <span v-if="errorMsg" class="kp-error">{{ errorMsg }}</span>
  </div>
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
      <div v-if="!data" class="kp-empty">
        <h2>暂无有效备料单</h2>
        <p class="muted">所有备料单均已作废（或尚未生成）。点击「生成备料单」开一张新单。</p>
      </div>
      <template v-else>
        <h2>备料单 #{{ data.id }} · {{ data.order?.code }} · {{ data.order?.outlet }}</h2>
        <table>
          <thead><tr><th>原料</th><th>需求</th><th>账面结存</th><th>本单预占</th><th>可用</th><th>单位</th></tr></thead>
          <tbody>
            <tr v-for="l in data.prep_lines" :key="l.ingredient_id">
              <td>{{ l.ingredient_name }}</td>
              <td>{{ l.need_qty }}</td>
              <td>{{ l.stock_qty }}</td>
              <td>{{ l.reserved_qty }}</td>
              <td>{{ l.available_qty }}</td>
              <td>{{ l.unit }}</td>
            </tr>
          </tbody>
        </table>
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
      <p v-else style="font-size:0.8rem;margin:0.5rem 0 0">无有效备料单</p>
    </aside>
  </div>
</template>
