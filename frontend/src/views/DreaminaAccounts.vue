<template>
  <div class="space-y-8 relative">
    <!-- 账号列表 -->
    <section class="rounded-3xl border border-border bg-card p-6">
      <!-- 第一行：搜索 + 选择信息 -->
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div class="grid w-full grid-cols-2 gap-3 sm:flex sm:w-auto sm:items-center">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索邮箱"
            class="w-full rounded-full border border-input bg-background px-4 py-2 text-sm sm:w-48"
          />
          <SelectMenu
            v-model="statusFilter"
            :options="statusOptions"
            class="!w-full sm:!w-40"
          />
        </div>
        <div class="flex w-full flex-wrap items-center gap-3 text-xs text-muted-foreground sm:w-auto sm:flex-nowrap">
          <Checkbox :modelValue="allSelected" @update:modelValue="toggleSelectAll">
            全选
          </Checkbox>
          <span>已选 {{ selectedIds.size }} / {{ filteredAccounts.length }} 个账户</span>
        </div>
      </div>

      <!-- 第二行：操作按钮 -->
      <div class="mt-4 flex flex-wrap items-center gap-2">
        <button
          class="rounded-full border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors
                 hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isLoading"
          @click="loadAccounts"
        >
          刷新列表
        </button>
        <button
          class="rounded-full border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors
                 hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isRegistering"
          @click="isRegisterOpen = true"
        >
          注册账户
        </button>
        <button
          class="rounded-full border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors
                 hover:border-primary hover:text-primary"
          @click="isTaskOpen = true"
        >
          任务管理
        </button>
        <button
          v-if="selectedIds.size > 0"
          class="rounded-full border border-rose-300 px-4 py-2 text-sm font-medium text-rose-600 transition-colors
                 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isOperating"
          @click="handleBulkDelete"
        >
          删除选中 ({{ selectedIds.size }})
        </button>
      </div>

      <!-- 表格 -->
      <div class="relative mt-6 overflow-x-auto overflow-y-visible">
        <table v-if="filteredAccounts.length" class="min-w-full text-left text-sm">
          <thead class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            <tr>
              <th class="py-3 pr-4">
                <Checkbox :modelValue="allSelected" @update:modelValue="toggleSelectAll" />
              </th>
              <th class="py-3 pr-6">邮箱</th>
              <th class="py-3 pr-6">Session</th>
              <th class="py-3 pr-6">状态</th>
              <th class="py-3 pr-6">创建时间</th>
              <th class="py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="text-sm text-foreground">
            <tr
              v-for="account in paginatedAccounts"
              :key="account.id"
              class="border-t border-border"
            >
              <td class="py-4 pr-4" @click.stop>
                <Checkbox
                  :modelValue="selectedIds.has(account.id)"
                  @update:modelValue="toggleSelect(account.id)"
                />
              </td>
              <td class="py-4 pr-6 font-mono text-xs">{{ account.email }}</td>
              <td class="py-4 pr-6 font-mono text-xs">
                <span v-if="account.session_id" class="text-emerald-600">
                  {{ account.session_id.slice(0, 16) }}...
                </span>
                <span v-else class="text-muted-foreground">-</span>
              </td>
              <td class="py-4 pr-6">
                <span
                  class="inline-flex items-center rounded-full border border-border px-3 py-1 text-xs"
                  :class="account.status === 'active'
                    ? 'text-emerald-600'
                    : 'text-muted-foreground'"
                >
                  {{ account.status === 'active' ? '正常' : '已禁用' }}
                </span>
              </td>
              <td class="py-4 pr-6 text-xs text-muted-foreground">
                {{ formatTime(account.created_at) }}
              </td>
              <td class="py-4 text-right">
                <div class="flex items-center justify-end gap-1">
                  <button
                    v-if="account.status === 'active'"
                    class="rounded-full border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors
                           hover:border-amber-400 hover:text-amber-600"
                    @click="handleDisable(account.id)"
                  >
                    禁用
                  </button>
                  <button
                    v-else
                    class="rounded-full border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors
                           hover:border-emerald-400 hover:text-emerald-600"
                    @click="handleEnable(account.id)"
                  >
                    启用
                  </button>
                  <button
                    class="rounded-full border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors
                           hover:border-rose-400 hover:text-rose-600"
                    @click="handleDelete(account.id)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else-if="!isLoading" class="py-8 text-center text-sm text-muted-foreground">
          暂无 Dreamina 账户
        </div>
        <div v-else class="py-8 text-center text-sm text-muted-foreground">
          加载中...
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="totalPages > 1" class="mt-4 flex items-center justify-center gap-2">
        <button
          class="rounded-full border border-border px-3 py-1 text-xs disabled:opacity-50"
          :disabled="currentPage <= 1"
          @click="currentPage--"
        >
          上一页
        </button>
        <span class="text-xs text-muted-foreground">{{ currentPage }} / {{ totalPages }}</span>
        <button
          class="rounded-full border border-border px-3 py-1 text-xs disabled:opacity-50"
          :disabled="currentPage >= totalPages"
          @click="currentPage++"
        >
          下一页
        </button>
      </div>
    </section>

    <!-- 注册弹窗 -->
    <Teleport to="body">
      <div v-if="isRegisterOpen" class="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 px-4">
        <div class="w-full max-w-lg rounded-3xl border border-border bg-card shadow-xl">
          <div class="flex items-center justify-between border-b border-border/60 px-6 py-4">
            <div>
              <p class="text-sm font-medium text-foreground">注册 Dreamina 账户</p>
              <p class="mt-1 text-xs text-muted-foreground">创建临时邮箱并自动注册 Dreamina</p>
            </div>
            <button
              class="text-xs text-muted-foreground transition-colors hover:text-foreground"
              @click="isRegisterOpen = false"
            >
              关闭
            </button>
          </div>
          <div class="space-y-4 px-6 py-4 text-sm">
            <div>
              <label class="block text-xs text-muted-foreground">临时邮箱服务</label>
              <SelectMenu
                v-model="registerMailProvider"
                :options="mailProviderOptions"
                class="mt-1 w-full"
              />
            </div>
            <div>
              <label class="block text-xs text-muted-foreground">注册数量</label>
              <input
                v-model.number="registerCount"
                type="number"
                min="1"
                class="mt-1 w-full rounded-2xl border border-input bg-background px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div class="flex items-center justify-end gap-2 border-t border-border/60 px-6 py-4">
            <button
              class="rounded-full border border-border px-4 py-2 text-sm text-muted-foreground transition-colors
                     hover:border-primary hover:text-primary"
              @click="isRegisterOpen = false"
            >
              取消
            </button>
            <button
              class="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity
                     hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="isRegistering"
              @click="handleRegister"
            >
              开始注册
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 任务管理弹窗 -->
    <Teleport to="body">
      <div v-if="isTaskOpen" class="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 px-4">
        <div class="flex h-[70vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-border bg-card shadow-xl">
          <div class="flex items-center justify-between border-b border-border/60 px-6 py-4">
            <div>
              <p class="text-sm font-medium text-foreground">Dreamina 任务管理</p>
              <p class="mt-1 text-xs text-muted-foreground">查看注册任务进度和日志</p>
            </div>
            <button
              class="text-xs text-muted-foreground transition-colors hover:text-foreground"
              @click="isTaskOpen = false"
            >
              关闭
            </button>
          </div>

          <!-- 任务信息 -->
          <div v-if="currentTask" class="px-6 py-4">
            <div class="space-y-1 text-xs text-muted-foreground">
              <div class="flex items-center justify-between gap-3 font-medium text-foreground">
                <div class="flex items-center gap-2">
                  <span
                    class="h-2.5 w-2.5 rounded-full"
                    :class="taskStatusClass"
                  ></span>
                  注册任务
                </div>
                <button
                  v-if="currentTask.status === 'running' || currentTask.status === 'pending'"
                  class="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors
                         hover:border-rose-500 hover:text-rose-600"
                  @click="handleCancelTask"
                >
                  中断
                </button>
              </div>
              <div class="flex flex-wrap gap-x-4 gap-y-1">
                <span>状态：{{ formatTaskStatus(currentTask.status) }}</span>
                <span>进度：{{ currentTask.progress }}/{{ currentTask.count }}</span>
                <span>成功：{{ currentTask.success_count }}</span>
                <span>失败：{{ currentTask.fail_count }}</span>
              </div>
            </div>
          </div>

          <!-- 日志区域 -->
          <div class="flex min-h-0 flex-1 flex-col px-6 pb-4">
            <div
              ref="logsRef"
              class="scrollbar-slim flex-1 overflow-y-auto rounded-2xl border border-border bg-muted/30 p-3"
            >
              <div v-if="taskLogs.length" class="space-y-1 text-[11px] text-muted-foreground">
                <div v-for="(log, index) in taskLogs" :key="index" class="font-mono">
                  <span class="text-muted-foreground/60">{{ formatLogTime(log.time) }}</span>
                  <span :class="log.level === 'error' ? 'text-rose-500' : log.level === 'warning' ? 'text-amber-500' : ''">
                    {{ log.message }}
                  </span>
                </div>
              </div>
              <div v-else class="text-xs text-muted-foreground">
                暂无任务日志
              </div>
            </div>
          </div>

          <div class="flex items-center justify-end gap-2 border-t border-border/60 px-6 py-4">
            <button
              class="rounded-full border border-border px-4 py-2 text-sm text-muted-foreground transition-colors
                     hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!taskLogs.length"
              @click="taskLogs = []"
            >
              清空日志
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import SelectMenu from '@/components/ui/SelectMenu.vue'
import { dreaminaApi } from '@/api/dreamina'
import type { RegisterTask } from '@/types/api'
import type { DreaminaAccount } from '@/api/dreamina'
import { mailProviderOptions, defaultMailProvider } from '@/constants/mailProviders'

// ==================== 状态 ====================

const accounts = ref<DreaminaAccount[]>([])
const isLoading = ref(false)
const isOperating = ref(false)
const isRegistering = ref(false)
const searchQuery = ref('')
const statusFilter = ref('all')
const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '正常', value: 'active' },
  { label: '已禁用', value: 'disabled' },
]
const selectedIds = ref(new Set<string>())
const currentPage = ref(1)
const pageSize = 20

// 注册弹窗
const isRegisterOpen = ref(false)
const registerCount = ref(1)
const registerMailProvider = ref(defaultMailProvider)

// 任务弹窗
const isTaskOpen = ref(false)
const currentTask = ref<RegisterTask | null>(null)
const taskLogs = ref<Array<{ time: string; level: string; message: string }>>([])
const logsRef = ref<HTMLElement | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ==================== 计算属性 ====================

const filteredAccounts = computed(() => {
  return accounts.value.filter(acc => {
    const matchSearch = !searchQuery.value || acc.email.includes(searchQuery.value)
    const matchStatus = statusFilter.value === 'all' || acc.status === statusFilter.value
    return matchSearch && matchStatus
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredAccounts.value.length / pageSize)))

const paginatedAccounts = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredAccounts.value.slice(start, start + pageSize)
})

const allSelected = computed(() => {
  if (!paginatedAccounts.value.length) return false
  return paginatedAccounts.value.every(a => selectedIds.value.has(a.id))
})

const taskStatusClass = computed(() => {
  if (!currentTask.value) return ''
  const s = currentTask.value.status
  if (s === 'running') return 'bg-blue-500 animate-pulse'
  if (s === 'pending') return 'bg-amber-500 animate-pulse'
  if (s === 'success') return 'bg-emerald-500'
  if (s === 'failed') return 'bg-rose-500'
  return 'bg-muted-foreground'
})

// ==================== 方法 ====================

function toggleSelectAll() {
  if (allSelected.value) {
    paginatedAccounts.value.forEach(a => selectedIds.value.delete(a.id))
  } else {
    paginatedAccounts.value.forEach(a => selectedIds.value.add(a.id))
  }
}

function toggleSelect(id: string) {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}

async function loadAccounts() {
  isLoading.value = true
  try {
    const data = await dreaminaApi.listAccounts()
    accounts.value = Array.isArray(data) ? data : []
  } catch (e) {
    console.error('加载 Dreamina 账户失败', e)
  } finally {
    isLoading.value = false
  }
}

async function handleDelete(id: string) {
  if (!confirm('确定删除此账户？')) return
  isOperating.value = true
  try {
    await dreaminaApi.deleteAccount(id)
    selectedIds.value.delete(id)
    await loadAccounts()
  } catch (e) {
    console.error('删除失败', e)
  } finally {
    isOperating.value = false
  }
}

async function handleBulkDelete() {
  const ids = Array.from(selectedIds.value)
  if (!confirm(`确定删除选中的 ${ids.length} 个账户？`)) return
  isOperating.value = true
  try {
    await dreaminaApi.bulkDelete(ids)
    selectedIds.value.clear()
    await loadAccounts()
  } catch (e) {
    console.error('批量删除失败', e)
  } finally {
    isOperating.value = false
  }
}

async function handleDisable(id: string) {
  try {
    await dreaminaApi.disableAccount(id)
    await loadAccounts()
  } catch (e) {
    console.error('禁用失败', e)
  }
}

async function handleEnable(id: string) {
  try {
    await dreaminaApi.enableAccount(id)
    await loadAccounts()
  } catch (e) {
    console.error('启用失败', e)
  }
}

async function handleRegister() {
  isRegistering.value = true
  isRegisterOpen.value = false
  isTaskOpen.value = true
  try {
    const count = registerCount.value > 0 ? registerCount.value : 1
    const task = await dreaminaApi.startRegister(count, undefined, registerMailProvider.value)
    currentTask.value = task
    taskLogs.value = task.logs || []
    startPolling(task.id)
  } catch (e) {
    console.error('启动注册失败', e)
    isRegistering.value = false
  }
}

async function handleCancelTask() {
  if (!currentTask.value) return
  try {
    await dreaminaApi.cancelRegisterTask(currentTask.value.id, '用户取消')
  } catch (e) {
    console.error('取消任务失败', e)
  }
}

function startPolling(taskId: string) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const task = await dreaminaApi.getRegisterTask(taskId)
      currentTask.value = task
      taskLogs.value = task.logs || []
      scrollLogsToBottom()

      if (task.status === 'success' || task.status === 'failed' || task.status === 'cancelled') {
        stopPolling()
        isRegistering.value = false
        loadAccounts()
      }
    } catch {
      stopPolling()
      isRegistering.value = false
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function scrollLogsToBottom() {
  nextTick(() => {
    if (logsRef.value) {
      logsRef.value.scrollTop = logsRef.value.scrollHeight
    }
  })
}

function formatTime(t: string) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN')
  } catch {
    return t
  }
}

function formatLogTime(t: string) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleTimeString('zh-CN') + ' '
  } catch {
    return t + ' '
  }
}

function formatTaskStatus(status: string) {
  const map: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    success: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[status] || status
}

// ==================== 生命周期 ====================

onMounted(async () => {
  await loadAccounts()
  // 检查是否有进行中的任务
  try {
    const task = await dreaminaApi.getRegisterCurrent()
    if ('id' in task && (task as RegisterTask).status) {
      const t = task as RegisterTask
      if (t.status === 'running' || t.status === 'pending') {
        currentTask.value = t
        taskLogs.value = t.logs || []
        isRegistering.value = true
        startPolling(t.id)
      }
    }
  } catch {
    // 无进行中任务
  }
})

onUnmounted(() => {
  stopPolling()
})

watch(searchQuery, () => {
  currentPage.value = 1
})

watch(statusFilter, () => {
  currentPage.value = 1
})
</script>
