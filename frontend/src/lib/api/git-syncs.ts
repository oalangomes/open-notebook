import apiClient from './client'

export interface GitSyncFileState {
  path: string
  raw_url?: string | null
  source_id?: string | null
  content_hash?: string | null
  command_id?: string | null
  command_updated_at?: string | null
  last_sync?: string | null
  last_status?: string | null
  last_error?: string | null
  active: boolean
}

export interface GitSyncPreviewItem {
  path: string
  source_type: 'explicit' | 'seed' | 'discovered'
  discovered_from?: string | null
  file_type?: string | null
}

export interface GitSyncPreviewResponse {
  items: GitSyncPreviewItem[]
  warnings: string[]
}

export interface GitSyncRunSummary {
  created: number
  updated: number
  repaired: number
  skipped: number
  failed: number
  filtered_out: number
  status_counts: Record<string, number>
  extension_counts: Record<string, Record<string, number>>
  started_at?: string | null
  completed_at?: string | null
}

export interface GitSyncResponse {
  id: string
  provider: 'azure_devops' | 'github'
  repo: string
  branch: string
  paths: string[]
  seed_paths: string[]
  max_discovery_depth: number
  max_discovery_files: number
  confirmed_paths: string[]
  include_extensions: string[]
  exclude_extensions: string[]
  credential_id?: string | null
  notebooks: string[]
  transformations: string[]
  embed: boolean
  refresh_interval?: string | null
  last_sync?: string | null
  last_status?: string | null
  last_error?: string | null
  last_run_summary?: GitSyncRunSummary | null
  file_states: GitSyncFileState[]
  created: string
  updated: string
}

export interface CreateGitSyncRequest {
  provider: 'azure_devops' | 'github'
  repo: string
  branch: string
  paths: string[]
  seed_paths?: string[]
  max_discovery_depth?: number
  max_discovery_files?: number
  confirmed_paths?: string[]
  include_extensions?: string[]
  exclude_extensions?: string[]
  credential_id?: string
  notebooks: string[]
  transformations: string[]
  embed: boolean
  refresh_interval?: string
}

export interface GitSyncRunResponse {
  sync_id: string
  summary: GitSyncRunSummary
  file_states: GitSyncFileState[]
}

export const gitSyncsApi = {
  preview: async (data: CreateGitSyncRequest): Promise<GitSyncPreviewResponse> => {
    const response = await apiClient.post<GitSyncPreviewResponse>('/git-syncs/preview', data)
    return response.data
  },

  create: async (data: CreateGitSyncRequest): Promise<GitSyncResponse> => {
    const response = await apiClient.post<GitSyncResponse>('/git-syncs', data)
    return response.data
  },

  run: async (syncId: string): Promise<GitSyncRunResponse> => {
    const response = await apiClient.post<GitSyncRunResponse>(`/git-syncs/${syncId}/run`)
    return response.data
  },
}
