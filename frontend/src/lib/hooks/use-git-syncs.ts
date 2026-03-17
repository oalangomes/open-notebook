import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  gitSyncsApi,
  CreateGitSyncRequest,
  GitSyncPreviewResponse,
  GitSyncRunResponse,
} from '@/lib/api/git-syncs'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'

export function useCreateGitSyncSource() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { language } = useTranslation()
  const isPortuguese = language === 'pt-BR'

  return useMutation({
    mutationFn: async (data: CreateGitSyncRequest): Promise<GitSyncRunResponse> => {
      const sync = await gitSyncsApi.create(data)
      return gitSyncsApi.run(sync.id)
    },
    onSuccess: (result, variables) => {
      variables.notebooks.forEach(notebookId => {
        queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.sources(notebookId),
          refetchType: 'active',
        })
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.sources(),
        refetchType: 'active',
      })

      const { created, updated, repaired, skipped, failed } = result.summary
      const description = isPortuguese
        ? `Sync concluído: ${created} criado(s), ${updated} atualizado(s), ${repaired} reparado(s), ${skipped} sem mudança, ${failed} falha(s).`
        : `Sync completed: ${created} created, ${updated} updated, ${repaired} repaired, ${skipped} unchanged, ${failed} failed.`

      toast({
        title: isPortuguese ? 'Fonte Git sincronizada' : 'Git source synced',
        description,
        variant: failed > 0 ? 'destructive' : 'default',
      })
    },
    onError: (error: unknown) => {
      toast({
        title: isPortuguese ? 'Erro' : 'Error',
        description: getApiErrorMessage(
          error,
          (key) => key,
          isPortuguese
            ? 'Falha ao criar a fonte Git privada'
            : 'Failed to create the private Git source'
        ),
        variant: 'destructive',
      })
    },
  })
}

export function usePreviewGitSyncSource() {
  const { toast } = useToast()
  const { language } = useTranslation()
  const isPortuguese = language === 'pt-BR'

  return useMutation({
    mutationFn: async (data: CreateGitSyncRequest): Promise<GitSyncPreviewResponse> => {
      return gitSyncsApi.preview(data)
    },
    onError: (error: unknown) => {
      toast({
        title: isPortuguese ? 'Erro' : 'Error',
        description: getApiErrorMessage(
          error,
          (key) => key,
          isPortuguese
            ? 'Falha ao identificar arquivos do repositório'
            : 'Failed to identify repository files'
        ),
        variant: 'destructive',
      })
    },
  })
}
