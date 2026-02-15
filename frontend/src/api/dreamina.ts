import apiClient from './client'
import type { RegisterTask } from '@/types/api'

export interface DreaminaAccount {
  id: string
  email: string
  session_id: string
  status: 'active' | 'expired' | 'disabled'
  created_at: string
  updated_at: string
}

export const dreaminaApi = {
  // 注册任务
  startRegister: (count?: number, domain?: string, mail_provider?: string) =>
    apiClient.post<never, RegisterTask>('/admin/dreamina/register/start', { count, domain, mail_provider }),

  getRegisterCurrent: () =>
    apiClient.get<never, RegisterTask | { status: string }>('/admin/dreamina/register/current'),

  getRegisterTask: (taskId: string) =>
    apiClient.get<never, RegisterTask>(`/admin/dreamina/register/task/${taskId}`),

  cancelRegisterTask: (taskId: string, reason?: string) =>
    apiClient.post<{ reason?: string }, RegisterTask>(`/admin/dreamina/register/cancel/${taskId}`, reason ? { reason } : {}),

  // 账号管理
  listAccounts: () =>
    apiClient.get<never, DreaminaAccount[]>('/admin/dreamina/accounts'),

  deleteAccount: (id: string) =>
    apiClient.delete(`/admin/dreamina/accounts/${id}`),

  disableAccount: (id: string) =>
    apiClient.put(`/admin/dreamina/accounts/${id}/disable`),

  enableAccount: (id: string) =>
    apiClient.put(`/admin/dreamina/accounts/${id}/enable`),

  bulkDelete: (ids: string[]) =>
    apiClient.post<never, { status: string; deleted: number }>('/admin/dreamina/accounts/bulk-delete', ids),
}
