'use client'

import { useState, useRef, useEffect, useMemo } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { LoaderIcon, CheckCircleIcon, XCircleIcon } from 'lucide-react'
import { toast } from 'sonner'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { WizardContainer, WizardStep } from '@/components/ui/wizard-container'
import { SourceTypeStep, parseAndValidateUrls } from './steps/SourceTypeStep'
import { GitSourcePreviewStep } from './steps/GitSourcePreviewStep'
import { NotebooksStep } from './steps/NotebooksStep'
import { ProcessingStep } from './steps/ProcessingStep'
import { useNotebooks } from '@/lib/hooks/use-notebooks'
import { useTransformations } from '@/lib/hooks/use-transformations'
import { useCreateSource } from '@/lib/hooks/use-sources'
import { useCreateGitSyncSource, usePreviewGitSyncSource } from '@/lib/hooks/use-git-syncs'
import { useSettings } from '@/lib/hooks/use-settings'
import { CreateSourceRequest } from '@/lib/types/api'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useCreateCredential, useCredentialsByProvider } from '@/lib/hooks/use-credentials'
import { GitSyncPreviewItem } from '@/lib/api/git-syncs'

const MAX_BATCH_SIZE = 50

const createSourceSchema = z.object({
  type: z.enum(['link', 'upload', 'text', 'git']),
  title: z.string().optional(),
  url: z.string().optional(),
  content: z.string().optional(),
  file: z.any().optional(),
  git_provider: z.enum(['azure_devops', 'github']).optional(),
  git_public: z.boolean().optional(),
  git_repo: z.string().optional(),
  git_branch: z.string().optional(),
  git_paths: z.string().optional(),
  git_seed_paths: z.string().optional(),
  git_include_extensions: z.string().optional(),
  git_exclude_extensions: z.string().optional(),
  git_max_discovery_depth: z.number().int().min(0).max(10).optional(),
  git_max_discovery_files: z.number().int().min(1).max(5000).optional(),
  git_credential_id: z.string().optional(),
  notebooks: z.array(z.string()).optional(),
  transformations: z.array(z.string()).optional(),
  embed: z.boolean(),
  async_processing: z.boolean(),
}).refine((data) => {
  if (data.type === 'link') {
    return !!data.url && data.url.trim() !== ''
  }
  if (data.type === 'text') {
    return !!data.content && data.content.trim() !== ''
  }
  if (data.type === 'upload') {
    if (data.file instanceof FileList) {
      return data.file.length > 0
    }
    return !!data.file
  }
  if (data.type === 'git') {
    return !!data.git_repo?.trim()
      && !!data.git_branch?.trim()
      && (!!data.git_paths?.trim() || !!data.git_seed_paths?.trim())
      && (
        data.git_provider === 'github'
          ? !!data.git_public || !!data.git_credential_id?.trim()
          : !!data.git_credential_id?.trim()
      )
  }
  return true
}, {
  message: 'Please provide the required content for the selected source type',
  path: ['type'],
}).refine((data) => {
  // Make title mandatory for text sources
  if (data.type === 'text') {
    return !!data.title && data.title.trim() !== ''
  }
  return true
}, {
  message: 'Title is required for text sources',
  path: ['title'],
})

type CreateSourceFormData = z.infer<typeof createSourceSchema>

interface AddSourceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultNotebookId?: string
}

interface ProcessingState {
  message: string
  progress?: number
}

interface BatchProgress {
  total: number
  completed: number
  failed: number
  currentItem?: string
}

interface GitCredentialFormState {
  provider: 'azure_devops' | 'github'
  name: string
  baseUrl: string
  apiKey: string
}

type WizardStepKey = 'source' | 'preview' | 'notebooks' | 'processing'

function normalizeGitHubRepoInput(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) {
    return trimmed
  }

  let normalized = trimmed
  let isGitHubUrl = false

  if (normalized.startsWith('git@github.com:')) {
    normalized = normalized.slice('git@github.com:'.length)
    isGitHubUrl = true
  } else if (normalized.startsWith('ssh://git@github.com/')) {
    normalized = normalized.slice('ssh://git@github.com/'.length)
    isGitHubUrl = true
  } else if (
    normalized.startsWith('https://github.com/')
    || normalized.startsWith('http://github.com/')
  ) {
    try {
      normalized = new URL(normalized).pathname.replace(/^\/+/, '')
      isGitHubUrl = true
    } catch {
      normalized = normalized
    }
  } else if (normalized.startsWith('github.com/')) {
    normalized = normalized.slice('github.com/'.length)
    isGitHubUrl = true
  }

  normalized = normalized.replace(/\/+$/, '').replace(/\.git$/, '')

  if (isGitHubUrl) {
    const parts = normalized.split('/').filter(Boolean)
    if (parts.length >= 2) {
      return `${parts[0]}/${parts[1]}`
    }
  }

  return normalized
}

export function AddSourceDialog({ 
  open, 
  onOpenChange, 
  defaultNotebookId 
}: AddSourceDialogProps) {
  const { t, language } = useTranslation()
  const isPortuguese = language === 'pt-BR'

  // Simplified state management
  const [currentStep, setCurrentStep] = useState(1)
  const [processing, setProcessing] = useState(false)
  const [processingStatus, setProcessingStatus] = useState<ProcessingState | null>(null)
  const [selectedNotebooks, setSelectedNotebooks] = useState<string[]>(
    defaultNotebookId ? [defaultNotebookId] : []
  )
  const [selectedTransformations, setSelectedTransformations] = useState<string[]>([])

  // Batch-specific state
  const [urlValidationErrors, setUrlValidationErrors] = useState<{ url: string; line: number }[]>([])
  const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(null)
  const [gitPreviewItems, setGitPreviewItems] = useState<GitSyncPreviewItem[]>([])
  const [gitPreviewWarnings, setGitPreviewWarnings] = useState<string[]>([])
  const [gitSelectedPaths, setGitSelectedPaths] = useState<string[]>([])

  // Cleanup timeouts to prevent memory leaks
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  // API hooks
  const createSource = useCreateSource()
  const createGitSyncSource = useCreateGitSyncSource()
  const previewGitSyncSource = usePreviewGitSyncSource()
  const createCredential = useCreateCredential()
  const { data: notebooks = [], isLoading: notebooksLoading } = useNotebooks()
  const { data: transformations = [], isLoading: transformationsLoading } = useTransformations()
  const { data: azureDevopsCredentials = [] } = useCredentialsByProvider('azure_devops')
  const { data: githubCredentials = [] } = useCredentialsByProvider('github')
  const { data: settings } = useSettings()

  const [gitCredentialDialogOpen, setGitCredentialDialogOpen] = useState(false)
  const [gitCredentialForm, setGitCredentialForm] = useState<GitCredentialFormState>({
    provider: 'azure_devops',
    name: '',
    baseUrl: '',
    apiKey: '',
  })

  // Form setup
  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    formState: { errors },
    reset,
  } = useForm<CreateSourceFormData>({
    resolver: zodResolver(createSourceSchema),
    defaultValues: {
      notebooks: defaultNotebookId ? [defaultNotebookId] : [],
      embed: settings?.default_embedding_option === 'always' || settings?.default_embedding_option === 'ask',
      async_processing: true,
      transformations: [],
      git_provider: 'azure_devops',
      git_public: false,
      git_max_discovery_depth: 2,
      git_max_discovery_files: 200,
    },
  })

  // Initialize form values when settings and transformations are loaded
  useEffect(() => {
    if (settings && transformations.length > 0) {
      const defaultTransformations = transformations
        .filter(t => t.apply_default)
        .map(t => t.id)

      setSelectedTransformations(defaultTransformations)

      // Reset form with proper embed value based on settings
      const embedValue = settings.default_embedding_option === 'always' ||
                         (settings.default_embedding_option === 'ask')

      reset({
        notebooks: defaultNotebookId ? [defaultNotebookId] : [],
        embed: embedValue,
        async_processing: true,
        transformations: [],
        git_provider: 'azure_devops',
        git_public: false,
        git_max_discovery_depth: 2,
        git_max_discovery_files: 200,
      })
    }
  }, [settings, transformations, defaultNotebookId, reset])

  // Cleanup effect
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  const selectedType = watch('type')
  const watchedUrl = watch('url')
  const watchedContent = watch('content')
  const watchedFile = watch('file')
  const watchedTitle = watch('title')
  const watchedGitPaths = watch('git_paths')
  const watchedGitSeedPaths = watch('git_seed_paths')
  const watchedGitProvider = watch('git_provider') || 'azure_devops'
  const watchedGitRepo = watch('git_repo')
  const watchedGitBranch = watch('git_branch')
  const watchedGitIncludeExtensions = watch('git_include_extensions')
  const watchedGitExcludeExtensions = watch('git_exclude_extensions')
  const watchedGitCredentialId = watch('git_credential_id')
  const watchedGitPublic = watch('git_public')

  const isGitFlow = selectedType === 'git'

  const stepKeys: WizardStepKey[] = useMemo(
    () => isGitFlow
      ? ['source', 'preview', 'notebooks', 'processing']
      : ['source', 'notebooks', 'processing'],
    [isGitFlow]
  )

  const WIZARD_STEPS: readonly WizardStep[] = useMemo(
    () => stepKeys.map((stepKey, index) => {
      if (stepKey === 'source') {
        return {
          number: index + 1,
          title: t.sources.addSource,
          description: t.sources.processDescription,
        }
      }
      if (stepKey === 'preview') {
        return {
          number: index + 1,
          title: isPortuguese ? 'Confirmar arquivos' : 'Confirm files',
          description: isPortuguese ? 'Revise os arquivos identificados' : 'Review identified files',
        }
      }
      if (stepKey === 'notebooks') {
        return {
          number: index + 1,
          title: t.navigation.notebooks,
          description: t.notebooks.searchPlaceholder,
        }
      }
      return {
        number: index + 1,
        title: t.navigation.process,
        description: t.sources.processDescription,
      }
    }),
    [isGitFlow, isPortuguese, stepKeys, t.navigation.notebooks, t.navigation.process, t.notebooks.searchPlaceholder, t.sources.addSource, t.sources.processDescription]
  )

  const totalSteps = stepKeys.length
  const getStepKey = (step: number): WizardStepKey => stepKeys[step - 1] || 'source'

  const gitCredentials = useMemo(
    () => watchedGitProvider === 'github' ? githubCredentials : azureDevopsCredentials,
    [azureDevopsCredentials, githubCredentials, watchedGitProvider]
  )

  useEffect(() => {
    const selectedCredentialId = watch('git_credential_id')
    if (!selectedCredentialId) {
      return
    }
    const hasSelectedCredential = gitCredentials.some(
      credential => credential.id === selectedCredentialId
    )
    if (!hasSelectedCredential) {
      setValue('git_credential_id', '', { shouldValidate: true })
    }
  }, [gitCredentials, setValue, watch, watchedGitProvider])

  useEffect(() => {
    setGitPreviewItems([])
    setGitPreviewWarnings([])
    setGitSelectedPaths([])
  }, [
    selectedType,
    watchedGitProvider,
    watchedGitPublic,
    watchedGitRepo,
    watchedGitBranch,
    watchedGitPaths,
    watchedGitSeedPaths,
    watchedGitIncludeExtensions,
    watchedGitExcludeExtensions,
    watchedGitCredentialId,
  ])

  // Batch mode detection
  const {
    isBatchMode,
    itemCount,
    parsedUrls,
    parsedFiles,
    parsedGitPaths,
    parsedGitSeedPaths,
    parsedGitIncludeExtensions,
    parsedGitExcludeExtensions,
  } = useMemo(() => {
    let urlCount = 0
    let fileCount = 0
    let parsedUrls: string[] = []
    let parsedFiles: File[] = []
    let parsedGitPaths: string[] = []
    let parsedGitSeedPaths: string[] = []
    let parsedGitIncludeExtensions: string[] = []
    let parsedGitExcludeExtensions: string[] = []

    if (selectedType === 'link' && watchedUrl) {
      const { valid } = parseAndValidateUrls(watchedUrl)
      parsedUrls = valid
      urlCount = valid.length
    }

    if (selectedType === 'upload' && watchedFile) {
      const fileList = watchedFile as FileList
      if (fileList?.length) {
        parsedFiles = Array.from(fileList)
        fileCount = parsedFiles.length
      }
    }

    if (selectedType === 'git' && watchedGitPaths) {
      parsedGitPaths = watchedGitPaths
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)
    }

    if (selectedType === 'git' && watchedGitSeedPaths) {
      parsedGitSeedPaths = watchedGitSeedPaths
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)
    }

    if (selectedType === 'git' && watchedGitIncludeExtensions) {
      parsedGitIncludeExtensions = watchedGitIncludeExtensions
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)
    }

    if (selectedType === 'git' && watchedGitExcludeExtensions) {
      parsedGitExcludeExtensions = watchedGitExcludeExtensions
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)
    }

    const isBatchMode = urlCount > 1 || fileCount > 1
    const itemCount = selectedType === 'link' ? urlCount : fileCount

    return {
      isBatchMode,
      itemCount,
      parsedUrls,
      parsedFiles,
      parsedGitPaths,
      parsedGitSeedPaths,
      parsedGitIncludeExtensions,
      parsedGitExcludeExtensions,
    }
  }, [
    selectedType,
    watchedUrl,
    watchedFile,
    watchedGitPaths,
    watchedGitSeedPaths,
    watchedGitIncludeExtensions,
    watchedGitExcludeExtensions,
  ])

  // Check for batch size limit
  const isOverLimit = itemCount > MAX_BATCH_SIZE

  // Step validation - now reactive with watched values
  const isStepValid = (step: number): boolean => {
    switch (getStepKey(step)) {
      case 'source':
        if (!selectedType) return false
        // Check batch size limit
        if (isOverLimit) return false
        // Check for URL validation errors
        if (urlValidationErrors.length > 0) return false

        if (selectedType === 'link') {
          // In batch mode, check that we have at least one valid URL
          if (isBatchMode) {
            return parsedUrls.length > 0
          }
          return !!watchedUrl && watchedUrl.trim() !== ''
        }
        if (selectedType === 'text') {
          return !!watchedContent && watchedContent.trim() !== '' &&
                 !!watchedTitle && watchedTitle.trim() !== ''
        }
        if (selectedType === 'upload') {
          if (watchedFile instanceof FileList) {
            return watchedFile.length > 0 && watchedFile.length <= MAX_BATCH_SIZE
          }
          return !!watchedFile
        }
        if (selectedType === 'git') {
          return !!watch('git_repo')?.trim()
            && !!watch('git_branch')?.trim()
            && (parsedGitPaths.length > 0 || parsedGitSeedPaths.length > 0)
            && (
              watch('git_provider') === 'github'
                ? !!watch('git_public') || !!watch('git_credential_id')?.trim()
                : !!watch('git_credential_id')?.trim()
            )
        }
        return true
      case 'preview':
        return gitPreviewItems.length > 0 && gitSelectedPaths.length > 0
      case 'notebooks':
      case 'processing':
        return true
      default:
        return false
    }
  }

  const buildGitSyncRequest = (data: CreateSourceFormData, confirmedPaths?: string[]) => {
    const provider = data.git_provider || 'azure_devops'
    const repo = provider === 'github'
      ? normalizeGitHubRepoInput(data.git_repo || '')
      : data.git_repo!.trim()

    return {
      provider,
      repo,
      branch: data.git_branch!.trim(),
      paths: parsedGitPaths,
      seed_paths: parsedGitSeedPaths,
      include_extensions: parsedGitIncludeExtensions,
      exclude_extensions: parsedGitExcludeExtensions,
      max_discovery_depth: data.git_max_discovery_depth,
      max_discovery_files: data.git_max_discovery_files,
      confirmed_paths: confirmedPaths,
      credential_id: data.git_credential_id?.trim() || undefined,
      notebooks: selectedNotebooks,
      transformations: selectedTransformations,
      embed: data.embed,
    }
  }

  const handleGitPreview = async (): Promise<boolean> => {
    const formData = watch()
    const preview = await previewGitSyncSource.mutateAsync(buildGitSyncRequest(formData))
    setGitPreviewItems(preview.items)
    setGitPreviewWarnings(preview.warnings)
    setGitSelectedPaths(preview.items.map(item => item.path))
    if (preview.items.length === 0) {
      toast.error(
        isPortuguese
          ? 'Nenhum arquivo elegível foi identificado para importar.'
          : 'No eligible files were identified for import.'
      )
      return false
    }
    return true
  }

  // Navigation
  const handleNextStep = async (e?: React.MouseEvent) => {
    e?.preventDefault()
    e?.stopPropagation()

    // Validate URLs when leaving step 1 in link mode
    if (getStepKey(currentStep) === 'source' && selectedType === 'link' && watchedUrl) {
      const { invalid } = parseAndValidateUrls(watchedUrl)
      if (invalid.length > 0) {
        setUrlValidationErrors(invalid)
        return
      }
      setUrlValidationErrors([])
    }

    if (!isStepValid(currentStep)) {
      return
    }

    if (getStepKey(currentStep) === 'source' && selectedType === 'git') {
      const hasPreviewItems = await handleGitPreview()
      if (!hasPreviewItems) {
        return
      }
    }

    if (currentStep < totalSteps) {
      setCurrentStep(currentStep + 1)
    }
  }

  // Clear URL validation errors when user edits
  const handleClearUrlErrors = () => {
    setUrlValidationErrors([])
  }

  const handlePrevStep = (e?: React.MouseEvent) => {
    e?.preventDefault()
    e?.stopPropagation()
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1)
    }
  }

  const handleStepClick = async (step: number) => {
    if (step <= currentStep) {
      setCurrentStep(step)
      return
    }

    if (step !== currentStep + 1 || !isStepValid(currentStep)) {
      return
    }

    if (getStepKey(currentStep) === 'source' && selectedType === 'git') {
      const hasPreviewItems = await handleGitPreview()
      if (!hasPreviewItems) {
        return
      }
    }

    setCurrentStep(step)
  }

  // Selection handlers
  const handleNotebookToggle = (notebookId: string) => {
    const updated = selectedNotebooks.includes(notebookId)
      ? selectedNotebooks.filter(id => id !== notebookId)
      : [...selectedNotebooks, notebookId]
    setSelectedNotebooks(updated)
  }

  const handleTransformationToggle = (transformationId: string) => {
    const updated = selectedTransformations.includes(transformationId)
      ? selectedTransformations.filter(id => id !== transformationId)
      : [...selectedTransformations, transformationId]
    setSelectedTransformations(updated)
  }

  const handleGitPreviewToggle = (path: string) => {
    setGitSelectedPaths(prev => (
      prev.includes(path)
        ? prev.filter(item => item !== path)
        : [...prev, path]
    ))
  }

  const handleSelectAllGitPreviewPaths = () => {
    setGitSelectedPaths(gitPreviewItems.map(item => item.path))
  }

  const handleClearGitPreviewPaths = () => {
    setGitSelectedPaths([])
  }

  const handleGitCredentialFieldChange = (
    field: keyof GitCredentialFormState,
    value: string
  ) => {
    setGitCredentialForm(prev => ({ ...prev, [field]: value }))
  }

  const handleCreateGitCredential = async () => {
    const provider = gitCredentialForm.provider
    const name = gitCredentialForm.name.trim()
    const baseUrl = gitCredentialForm.baseUrl.trim()
    const apiKey = gitCredentialForm.apiKey.trim()

    if (!name || !apiKey || (provider === 'azure_devops' && !baseUrl)) {
      toast.error(
        provider === 'github'
          ? (
            isPortuguese
              ? 'Preencha nome e PAT para salvar a credencial GitHub.'
              : 'Fill in name and PAT to save the GitHub credential.'
          )
          : (
            isPortuguese
              ? 'Preencha nome, URL base e PAT para salvar a credencial.'
              : 'Fill in name, base URL, and PAT to save the credential.'
          )
      )
      return
    }

    try {
      const credential = await createCredential.mutateAsync({
        name,
        provider,
        modalities: ['source_sync'],
        base_url: provider === 'azure_devops' ? baseUrl : undefined,
        api_key: apiKey,
      })

      setValue('git_credential_id', credential.id, { shouldValidate: true })
      setGitCredentialDialogOpen(false)
      setGitCredentialForm({
        provider,
        name: '',
        baseUrl: '',
        apiKey: '',
      })
    } catch {
      // Toast is already handled by the credential mutation hook.
    }
  }

  // Single source submission
  const submitSingleSource = async (data: CreateSourceFormData): Promise<void> => {
    if (data.type === 'git') {
      await createGitSyncSource.mutateAsync(
        buildGitSyncRequest(data, gitSelectedPaths)
      )
      return
    }

    const createRequest: CreateSourceRequest = {
      type: data.type as 'link' | 'upload' | 'text',
      notebooks: selectedNotebooks,
      url: data.type === 'link' ? data.url : undefined,
      content: data.type === 'text' ? data.content : undefined,
      title: data.title,
      transformations: selectedTransformations,
      embed: data.embed,
      delete_source: false,
      async_processing: true,
    }

    if (data.type === 'upload' && data.file) {
      const file = data.file instanceof FileList ? data.file[0] : data.file
      const requestWithFile = createRequest as CreateSourceRequest & { file?: File }
      requestWithFile.file = file
    }

    await createSource.mutateAsync(createRequest)
  }

  // Batch submission
  const submitBatch = async (data: CreateSourceFormData): Promise<{ success: number; failed: number }> => {
    const results = { success: 0, failed: 0 }
    const items: { type: 'url' | 'file'; value: string | File }[] = []

    // Collect items to process
    if (data.type === 'link' && parsedUrls.length > 0) {
      parsedUrls.forEach(url => items.push({ type: 'url', value: url }))
    } else if (data.type === 'upload' && parsedFiles.length > 0) {
      parsedFiles.forEach(file => items.push({ type: 'file', value: file }))
    }

    setBatchProgress({
      total: items.length,
      completed: 0,
      failed: 0,
    })

    // Process each item sequentially
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      const itemLabel = item.type === 'url'
        ? (item.value as string).substring(0, 50) + '...'
        : (item.value as File).name

      setBatchProgress(prev => prev ? {
        ...prev,
        currentItem: itemLabel,
      } : null)

      try {
        const createRequest: CreateSourceRequest = {
          type: item.type === 'url' ? 'link' : 'upload',
          notebooks: selectedNotebooks,
          url: item.type === 'url' ? item.value as string : undefined,
          transformations: selectedTransformations,
          embed: data.embed,
          delete_source: false,
          async_processing: true,
        }

        if (item.type === 'file') {
          const requestWithFile = createRequest as CreateSourceRequest & { file?: File }
          requestWithFile.file = item.value as File
        }

        await createSource.mutateAsync(createRequest)
        results.success++
      } catch (error) {
        console.error(`Error creating source for ${itemLabel}:`, error)
        results.failed++
      }

      setBatchProgress(prev => prev ? {
        ...prev,
        completed: results.success,
        failed: results.failed,
      } : null)
    }

    return results
  }

  // Form submission
  const onSubmit = async (data: CreateSourceFormData) => {
    try {
      setProcessing(true)

      if (isBatchMode) {
        // Batch submission
        setProcessingStatus({ message: t.sources.processingFiles })
        const results = await submitBatch(data)

        // Show summary toast
        if (results.failed === 0) {
          toast.success(t.sources.batchSuccess.replace('{count}', results.success.toString()))
        } else if (results.success === 0) {
          toast.error(t.sources.batchFailed.replace('{count}', results.failed.toString()))
        } else {
          toast.warning(t.sources.batchPartial.replace('{success}', results.success.toString()).replace('{failed}', results.failed.toString()))
        }

        handleClose()
      } else {
        // Single source submission
        setProcessingStatus({
          message: data.type === 'git'
            ? (isPortuguese ? 'Sincronizando arquivos do repositório privado...' : 'Syncing files from the private repository...')
            : t.sources.submittingSource,
        })
        await submitSingleSource(data)
        handleClose()
      }
    } catch (error) {
      console.error('Error creating source:', error)
      setProcessingStatus({
        message: t.common.error,
      })
      timeoutRef.current = setTimeout(() => {
        setProcessing(false)
        setProcessingStatus(null)
        setBatchProgress(null)
      }, 3000)
    }
  }

  // Dialog management
  const handleClose = () => {
    // Clear any pending timeouts
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }

    reset()
    setCurrentStep(1)
    setProcessing(false)
    setProcessingStatus(null)
    setSelectedNotebooks(defaultNotebookId ? [defaultNotebookId] : [])
    setUrlValidationErrors([])
    setBatchProgress(null)
    setGitPreviewItems([])
    setGitPreviewWarnings([])
    setGitSelectedPaths([])
    setGitCredentialDialogOpen(false)
    setGitCredentialForm({ provider: watchedGitProvider, name: '', baseUrl: '', apiKey: '' })

    // Reset to default transformations
    if (transformations.length > 0) {
      const defaultTransformations = transformations
        .filter(t => t.apply_default)
        .map(t => t.id)
      setSelectedTransformations(defaultTransformations)
    } else {
      setSelectedTransformations([])
    }

    onOpenChange(false)
  }

  // Processing view
  if (processing) {
    const progressPercent = batchProgress
      ? Math.round(((batchProgress.completed + batchProgress.failed) / batchProgress.total) * 100)
      : undefined

    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="sm:max-w-[500px]" showCloseButton={true}>
          <DialogHeader>
            <DialogTitle>
              {batchProgress ? t.sources.processingFiles : t.sources.statusProcessing}
            </DialogTitle>
            <DialogDescription>
              {batchProgress
                ? t.sources.processingBatchSources.replace('{count}', batchProgress.total.toString())
                : t.sources.processingSource
              }
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="flex items-center gap-3">
              <LoaderIcon className="h-5 w-5 animate-spin text-primary" />
              <span className="text-sm text-muted-foreground">
                {processingStatus?.message || t.common.processing}
              </span>
            </div>

            {/* Batch progress */}
            {batchProgress && (
              <>
                <div className="w-full bg-muted rounded-full h-2">
                  <div
                    className="bg-primary h-2 rounded-full transition-all duration-300"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>

                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-4">
                    <span className="flex items-center gap-1.5 text-green-600">
                      <CheckCircleIcon className="h-4 w-4" />
                      {batchProgress.completed} {t.common.completed}
                    </span>
                    {batchProgress.failed > 0 && (
                      <span className="flex items-center gap-1.5 text-destructive">
                        <XCircleIcon className="h-4 w-4" />
                        {batchProgress.failed} {t.common.failed}
                      </span>
                    )}
                  </div>
                   <span className="text-muted-foreground">
                    {batchProgress.completed + batchProgress.failed} / {batchProgress.total}
                  </span>
                </div>

                {batchProgress.currentItem && (
                  <p className="text-xs text-muted-foreground truncate">
                    {t.common.current}: {batchProgress.currentItem}
                  </p>
                )}
              </>
            )}

            {/* Single source progress */}
            {!batchProgress && processingStatus?.progress && (
              <div className="w-full bg-muted rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all duration-300"
                  style={{ width: `${processingStatus.progress}%` }}
                />
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  const currentStepValid = isStepValid(currentStep)
  const isSubmitting = createSource.isPending || createGitSyncSource.isPending || previewGitSyncSource.isPending

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-h-[92vh] overflow-hidden sm:max-w-[760px] p-0">
        <DialogHeader className="px-6 pt-6 pb-0">
          <DialogTitle>{t.sources.addNew}</DialogTitle>
          <DialogDescription>
            {t.sources.processDescription}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="min-w-0">
          <WizardContainer
            currentStep={currentStep}
            steps={WIZARD_STEPS}
            onStepClick={handleStepClick}
            className="border-0"
          >
            {getStepKey(currentStep) === 'source' && (
              <SourceTypeStep
                // @ts-expect-error - Type inference issue with zod schema
                control={control}
                register={register}
                setValue={setValue}
                // @ts-expect-error - Type inference issue with zod schema
                errors={errors}
                urlValidationErrors={urlValidationErrors}
                onClearUrlErrors={handleClearUrlErrors}
                gitCredentials={gitCredentials}
                onOpenGitCredentialDialog={() => {
                  setGitCredentialForm(prev => ({
                    ...prev,
                    provider: watchedGitProvider,
                    baseUrl: watchedGitProvider === 'github' ? '' : prev.baseUrl,
                  }))
                  setGitCredentialDialogOpen(true)
                }}
              />
            )}

            {getStepKey(currentStep) === 'preview' && (
              <GitSourcePreviewStep
                items={gitPreviewItems}
                warnings={gitPreviewWarnings}
                includeExtensions={parsedGitIncludeExtensions}
                excludeExtensions={parsedGitExcludeExtensions}
                selectedPaths={gitSelectedPaths}
                isPortuguese={isPortuguese}
                onTogglePath={handleGitPreviewToggle}
                onSelectAll={handleSelectAllGitPreviewPaths}
                onClearSelection={handleClearGitPreviewPaths}
              />
            )}

            {getStepKey(currentStep) === 'notebooks' && (
              <NotebooksStep
                notebooks={notebooks}
                selectedNotebooks={selectedNotebooks}
                onToggleNotebook={handleNotebookToggle}
                loading={notebooksLoading}
              />
            )}

            {getStepKey(currentStep) === 'processing' && (
              <ProcessingStep
                // @ts-expect-error - Type inference issue with zod schema
                control={control}
                transformations={transformations}
                selectedTransformations={selectedTransformations}
                onToggleTransformation={handleTransformationToggle}
                loading={transformationsLoading}
                settings={settings}
              />
            )}
          </WizardContainer>

          {/* Navigation */}
          <div className="flex justify-between items-center px-6 py-4 border-t border-border bg-muted">
            <Button 
              type="button" 
              variant="outline" 
              onClick={handleClose}
            >
              {t.common.cancel}
            </Button>

            <div className="flex gap-2">
              {currentStep > 1 && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={handlePrevStep}
                >
                  {t.common.back}
                </Button>
              )}

              {/* Show Next button on steps 1 and 2, styled as outline/secondary */}
              {currentStep < totalSteps && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={(e) => { void handleNextStep(e) }}
                  disabled={!currentStepValid || previewGitSyncSource.isPending}
                >
                  {previewGitSyncSource.isPending
                    ? (isPortuguese ? 'Identificando...' : 'Discovering...')
                    : t.common.next}
                </Button>
              )}

              {/* Show Done button on all steps, styled as primary */}
              <Button
                type="submit"
                disabled={!currentStepValid || getStepKey(currentStep) !== 'processing' || isSubmitting}
                className="min-w-[120px]"
              >
                {isSubmitting ? t.common.adding : t.common.done}
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>

      <Dialog open={gitCredentialDialogOpen} onOpenChange={setGitCredentialDialogOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>
              {gitCredentialForm.provider === 'github'
                ? (isPortuguese ? 'Nova credencial GitHub' : 'New GitHub credential')
                : (isPortuguese ? 'Nova credencial Azure DevOps' : 'New Azure DevOps credential')}
            </DialogTitle>
            <DialogDescription>
              {gitCredentialForm.provider === 'github'
                ? (
                  isPortuguese
                    ? 'Salve o PAT do GitHub para acessar repositórios privados ou evitar limites de uso.'
                    : 'Save the GitHub PAT to access private repositories or avoid rate limits.'
                )
                : (
                  isPortuguese
                    ? 'Salve o PAT e a URL base para acessar o repositório privado via RAW.'
                    : 'Save the PAT and base URL used to access the private repository through RAW.'
                )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {isPortuguese ? 'Nome da credencial' : 'Credential name'}
              </label>
              <input
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={gitCredentialForm.name}
                onChange={(e) => handleGitCredentialFieldChange('name', e.target.value)}
                placeholder={isPortuguese ? 'Azure DevOps Produção' : 'Azure DevOps Production'}
              />
            </div>

            {gitCredentialForm.provider === 'azure_devops' && (
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {isPortuguese ? 'URL base do Azure DevOps' : 'Azure DevOps base URL'}
                </label>
                <input
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={gitCredentialForm.baseUrl}
                  onChange={(e) => handleGitCredentialFieldChange('baseUrl', e.target.value)}
                  placeholder="https://dev.azure.com/your-org/your-project"
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium">PAT</label>
              <input
                type="password"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={gitCredentialForm.apiKey}
                onChange={(e) => handleGitCredentialFieldChange('apiKey', e.target.value)}
                placeholder={isPortuguese ? 'Cole o token de acesso pessoal' : 'Paste the personal access token'}
              />
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setGitCredentialDialogOpen(false)}
              disabled={createCredential.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              onClick={handleCreateGitCredential}
              disabled={createCredential.isPending}
            >
              {createCredential.isPending ? t.common.saving : (isPortuguese ? 'Salvar credencial' : 'Save credential')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Dialog>
  )
}
