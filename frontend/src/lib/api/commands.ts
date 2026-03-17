import apiClient from './client'

export interface SourceQueueJob {
  job_id: string
  app?: string | null
  command?: string | null
  status: string
  result?: Record<string, unknown> | null
  error_message?: string | null
  created?: string | null
  updated?: string | null
  progress?: Record<string, unknown> | null
  source_id?: string | null
  source_title?: string | null
  source_path?: string | null
  source_url?: string | null
  can_cancel: boolean
}

export interface CancelCommandResponse {
  job_id: string
  cancelled: boolean
  status: string
}

export const commandsApi = {
  listSourceQueue: async (status?: string, limit = 100): Promise<SourceQueueJob[]> => {
    const response = await apiClient.get<SourceQueueJob[]>('/commands/jobs', {
      params: {
        source_only: true,
        status_filter: status || undefined,
        limit,
      },
    })
    return response.data
  },

  cancelJob: async (jobId: string): Promise<CancelCommandResponse> => {
    const response = await apiClient.delete<CancelCommandResponse>(`/commands/jobs/${jobId}`)
    return response.data
  },
}
