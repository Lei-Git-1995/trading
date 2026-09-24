<script setup>
import {computed, h, onMounted, onUnmounted, reactive, ref, watch} from 'vue'
import {useRouter} from 'vue-router'
import {
  NButton, NCard, NDataTable, NDatePicker, NEmpty,
  NSelect, NSpace, NSpin, NTag, NTooltip, useMessage
} from 'naive-ui'
import {EventsEmit, EventsOff, EventsOn} from '../../wailsjs/runtime'
import {
  DeleteMorningStrategy, GenerateMorningStrategyNow, GetAiConfigs, GetConfig,
  GetMorningStrategyByDate, GetMorningStrategyList, GetPromptTemplates
} from '../../wailsjs/go/main/App'
import {MdPreview} from 'md-editor-v3'
import 'md-editor-v3/lib/preview.css'

const message = useMessage()
const router = useRouter()

// 日期选择（默认今天）
const selectedDate = ref(Date.now())
const dateStr = computed(() => {
  const d = new Date(selectedDate.value)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

function disableFutureDate(ts) {
  return ts > Date.now()
}

// 报告数据
const report = ref(null)
const loadingReport = ref(false)
// 历史列表
const historyList = ref([])
const historyLoading = ref(false)
const paginationReactive = reactive({
  page: 1,
  pageSize: 10,
  pageCount: 1,
  itemCount: 0,
  showSizePicker: true,
  pageSizes: [10, 20, 50],
  onChange: (page) => {
    paginationReactive.page = page
    loadHistory()
  },
  onUpdatePageSize: (pageSize) => {
    paginationReactive.pageSize = pageSize
    paginationReactive.page = 1
    loadHistory()
  }
})

// 高级选项
const aiConfigOptions = ref([])
const aiConfigId = ref(0)
const sysPromptId = ref(0)
// 提示词模板下拉选项
const promptOptions = ref([{label: '内置盘前策略提示词', value: 0}])
// AI 分析模式
const agentMode = ref('')
const agentModeOptions = [
  {label: '🤖 自动选择', value: ''},
  {label: '⚡ 快速模式', value: 'react'},
  {label: '🧠 规划模式', value: 'plan_execute'},
  {label: '🔬 DeepAgents', value: 'deepagents'}
]

// 主题（MdPreview）
const mdTheme = ref('dark')

// 流式输出内容（生成过程中实时展示，完成后清空）
const streamingContent = ref('')

// 记住用户上次的选择（AI 配置/提示词模板/分析模式），下次打开自动恢复
const choiceStorageKey = 'morningStrategyUserChoice'

function persistChoice() {
  localStorage.setItem(choiceStorageKey, JSON.stringify({
    aiConfigId: aiConfigId.value,
    sysPromptId: sysPromptId.value,
    agentMode: agentMode.value
  }))
}

function restoreChoice() {
  try {
    const saved = JSON.parse(localStorage.getItem(choiceStorageKey) || '{}')
    if (saved.aiConfigId > 0) {
      aiConfigId.value = saved.aiConfigId
    }
    if (saved.sysPromptId > 0) {
      sysPromptId.value = saved.sysPromptId
    }
    if (saved.agentMode && agentModeOptions.some(o => o.value === saved.agentMode)) {
      agentMode.value = saved.agentMode
    }
  } catch (e) {
    // 损坏数据忽略，使用默认值
  }
}

watch([aiConfigId, sysPromptId, agentMode], persistChoice)

const statusTagMap = {
  pending: {label: '待生成', type: 'default'},
  generating: {label: '生成中', type: 'info'},
  success: {label: '已生成', type: 'success'},
  failed: {label: '生成失败', type: 'error'}
}

function statusTag(status) {
  return statusTagMap[status] || {label: status, type: 'default'}
}

const isGenerating = computed(() => report.value?.status === 'generating')

// 加载当前日期策略
async function loadReport() {
  loadingReport.value = true
  try {
    report.value = await GetMorningStrategyByDate(dateStr.value)
  } catch (e) {
    console.error('加载盘前策略失败', e)
  } finally {
    loadingReport.value = false
  }
}

// 加载历史列表
async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await GetMorningStrategyList(paginationReactive.page, paginationReactive.pageSize)
    if (res) {
      historyList.value = res.list || []
      paginationReactive.itemCount = res.total || 0
      paginationReactive.pageCount = Math.max(1, Math.ceil((res.total || 0) / paginationReactive.pageSize))
    }
  } catch (e) {
    console.error('加载盘前策略历史失败', e)
  } finally {
    historyLoading.value = false
  }
}

// 手动生成/重新生成
function handleGenerate() {
  // 清空上次的流式内容并乐观置为生成中（后端立即推送流式进度与完成事件）
  streamingContent.value = ''
  report.value = {...(report.value || {}), strategyDate: dateStr.value, status: 'generating', content: ''}
  GenerateMorningStrategyNow(dateStr.value, aiConfigId.value, sysPromptId.value, agentMode.value).then(res => {
    message.success(res || '已开始生成，完成后自动展示')
    pollStatus()
  }).catch(e => {
    message.error('生成失败：' + e)
  })
}

// 轮询生成状态（每 5 秒一次，最多 60 次 = 5 分钟）
let pollTimer = null

function pollStatus() {
  stopPoll()
  let count = 0
  pollTimer = setInterval(async () => {
    count++
    if (count > 60) {
      stopPoll()
      return
    }
    try {
      const r = await GetMorningStrategyByDate(dateStr.value)
      if (r && r.status !== 'generating') {
        report.value = r
        streamingContent.value = ''
        loadHistory()
        stopPoll()
      } else if (r && r.status === 'generating' && (!report.value || report.value.status !== 'generating')) {
        report.value = r
      }
    } catch (e) {
      // 忽略轮询错误
    }
  }, 5000)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// 日期切换
function handleDateChange() {
  loadReport()
}

// 查看历史某天
function handleView(row) {
  const d = new Date(row.strategyDate + 'T00:00:00')
  selectedDate.value = d.getTime()
  loadReport()
}

// 删除
function handleDelete(row) {
  DeleteMorningStrategy(row.id).then(res => {
    if (res === '删除成功') {
      message.success(res)
      if (report.value && report.value.id === row.id) {
        loadReport()
      }
      loadHistory()
    } else {
      message.error(res)
    }
  })
}

// 保存为 Markdown 文件（前端 Blob 下载）
function handleSaveMarkdown() {
  if (!report.value || !report.value.content) {
    message.warning('暂无策略内容可保存')
    return
  }
  const blob = new Blob([report.value.content], {type: 'text/markdown;charset=utf-8'})
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `盘前策略_${report.value.strategyDate}.md`
  a.click()
  URL.revokeObjectURL(url)
}

// 跳转研究中心查看当日个股操作计划
function gotoOperationPlan() {
  router.push({name: 'research', query: {name: '研究中心'}})
  setTimeout(() => {
    EventsEmit("changeResearchTab", {name: '每日操作计划'})
  }, 100)
}

// 加载 AI 配置
async function loadAiConfigs() {
  try {
    const configs = await GetAiConfigs()
    aiConfigOptions.value = [
      {label: '默认（第一个AI配置）', value: 0},
      ...(configs || []).map(c => ({label: `${c.name}[${c.modelName}]`, value: c.ID}))
    ]
    // 恢复的选择已失效（配置被删除）时回退默认
    if (!aiConfigOptions.value.some(o => o.value === aiConfigId.value)) {
      aiConfigId.value = 0
    }
  } catch (e) {
    console.error('加载 AI 配置失败', e)
  }
}

// 加载提示词模板列表
async function loadPromptTemplates() {
  try {
    const templates = await GetPromptTemplates('', '')
    if (templates && templates.length > 0) {
      promptOptions.value = [
        {label: '内置盘前策略提示词', value: 0},
        ...templates.map(t => ({label: `${t.name}（${t.type}）`, value: t.ID}))
      ]
      // 恢复的选择已失效（模板被删除）时回退内置提示词
      if (!promptOptions.value.some(o => o.value === sysPromptId.value)) {
        sysPromptId.value = 0
      }
    }
  } catch (e) {
    console.error('加载提示词模板失败', e)
  }
}

// 生成完成事件
function onGenerated(data) {
  if (data && data.date === dateStr.value) {
    streamingContent.value = ''
    loadReport()
    if (data.status === 'failed') {
      message.error(`盘前策略生成失败：${data.errorMessage || '未知错误'}`)
    } else if (data.status === 'success') {
      message.success(`盘前策略已生成（${data.date}）`)
    }
  }
  loadHistory()
}

// 流式进度事件：实时追加 AI 输出内容
function onProgress(data) {
  if (data && data.date === dateStr.value) {
    if (!report.value || report.value.status !== 'generating') {
      report.value = {...(report.value || {}), strategyDate: dateStr.value, status: 'generating'}
    }
    streamingContent.value += (data.chunk || '')
  }
}

// 历史表格列
const columnsRef = [
  {title: '策略日期', key: 'strategyDate', width: 110},
  {
    title: '状态', key: 'status', width: 90, render(row) {
      const t = statusTag(row.status)
      return h(NTag, {type: t.type, size: 'small'}, {default: () => t.label})
    }
  },
  {
    title: '触发方式', key: 'triggerType', width: 90, render(row) {
      return row.triggerType === 'cron' ? '定时' : '手动'
    }
  },
  {
    title: '摘要', key: 'summary', ellipsis: {tooltip: true}, render(row) {
      return row.summary || '—'
    }
  },
  {
    title: '耗时', key: 'durationMs', width: 90, render(row) {
      if (!row.durationMs) return '—'
      if (row.durationMs < 1000) return row.durationMs + 'ms'
      return (row.durationMs / 1000).toFixed(1) + 's'
    }
  },
  {
    title: '操作', key: 'actions', width: 130, render(row) {
      return h(NSpace, {size: 4}, {
        default: () => [
          h(NButton, {size: 'tiny', onClick: () => handleView(row)}, {default: () => '查看'}),
          h(NButton, {size: 'tiny', type: 'error', onClick: () => handleDelete(row)}, {default: () => '删除'})
        ]
      })
    }
  }
]

onMounted(() => {
  GetConfig().then(result => {
    mdTheme.value = result && result.darkTheme ? 'dark' : 'light'
  })
  restoreChoice()
  loadAiConfigs()
  loadPromptTemplates()
  loadReport()
  loadHistory()
  EventsOn("morningStrategyGenerated", onGenerated)
  EventsOn("morningStrategyProgress", onProgress)
})
</script>

<template>
  <div style="text-align: left; padding: 8px 4px">
    <!-- 顶部操作条 -->
    <n-card size="small" style="margin-bottom: 10px">
      <n-space align="center" :wrap="true">
        <n-date-picker v-model:value="selectedDate" type="date" format="yyyy-MM-dd"
                       :is-date-disabled="disableFutureDate" style="width: 160px" @update:value="handleDateChange"/>
        <n-button type="primary" :loading="isGenerating" :disabled="isGenerating"
                  @click="handleGenerate">
          {{ report && report.status === 'success' ? '重新生成' : '立即生成' }}
        </n-button>
        <n-button :disabled="!report || report.status !== 'success'" @click="handleSaveMarkdown">
          保存为Markdown
        </n-button>
        <n-button @click="gotoOperationPlan">查看当日个股操作计划</n-button>
        <n-tag v-if="report" :type="statusTag(report.status).type" size="small">
          {{ statusTag(report.status).label }}
        </n-tag>
        <n-tag v-if="report && report.generatedAt" size="small" type="default">
          生成耗时 {{ report.durationMs < 1000 ? report.durationMs + 'ms' : (report.durationMs / 1000).toFixed(1) + 's' }}
        </n-tag>
        <n-tooltip v-if="report && report.status === 'failed'" trigger="hover">
          <template #trigger>
            <n-tag type="error" size="small" style="cursor: pointer">失败原因</n-tag>
          </template>
          {{ report.errorMessage || '未知错误' }}
        </n-tooltip>
        <div style="flex: 1"></div>
        <n-select v-model:value="aiConfigId" :options="aiConfigOptions"
                  style="width: 240px" size="small" placeholder="AI 配置"/>
      </n-space>
      <n-space align="center" :wrap="true" style="margin-top: 8px">
        <span style="font-size: 13px; min-width: 96px">AI 分析模式：</span>
        <n-select v-model:value="agentMode" :options="agentModeOptions"
                  style="width: 180px" size="small"/>
        <span style="font-size: 13px; min-width: 72px">提示词模板：</span>
        <n-select v-model:value="sysPromptId" :options="promptOptions" filterable
                  style="width: 280px" size="small" placeholder="选择提示词模板"/>
        <span style="font-size: 12px; color: #999">规划/DeepAgents 模式下 AI 可调用工具获取实时数据</span>
      </n-space>
    </n-card>

    <!-- 策略正文 -->
    <n-card title="盘前策略" size="small" style="margin-bottom: 10px">
      <!-- 流式生成中：实时渲染 AI 增量输出 -->
      <template v-if="isGenerating && streamingContent">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px; color: #999; font-size: 12px">
          <n-spin :size="14"/>
          <span>AI 正在流式生成盘前策略，以下为实时内容…</span>
        </div>
        <MdPreview :theme="mdTheme" :model-value="streamingContent"
                   editor-id="morning-strategy-streaming"/>
      </template>
      <n-spin v-else :show="isGenerating">
        <div v-if="isGenerating" style="padding: 60px 0; text-align: center">
          <div style="color: #999">AI 正在生成盘前策略，预计 1-3 分钟…</div>
          <div style="color: #666; font-size: 12px; margin-top: 6px">基于昨日复盘 + 隔夜外围 + 龙虎榜 + 自选股生成</div>
        </div>
        <div v-else-if="report && report.content" style="min-height: 200px">
          <MdPreview :theme="mdTheme" :model-value="report.content"
                     editor-id="morning-strategy-content"/>
        </div>
        <n-empty v-else description="当日暂无盘前策略" style="padding: 60px 0">
          <template #extra>
            <n-button type="primary" @click="handleGenerate">生成今日盘前策略</n-button>
          </template>
        </n-empty>
      </n-spin>
    </n-card>

    <!-- 历史列表 -->
    <n-card title="历史策略" size="small">
      <n-data-table :columns="columnsRef" :data="historyList" :loading="historyLoading"
                    :pagination="paginationReactive" size="small" striped/>
    </n-card>
  </div>
</template>

<style scoped>
:deep(.n-card-header__main) {
  text-align: left;
}

:deep(.n-form-item-label) {
  text-align: left;
}
</style>
