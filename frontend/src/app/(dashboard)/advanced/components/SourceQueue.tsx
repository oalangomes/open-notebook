'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw, CircleX, Clock3, CheckCircle2, AlertTriangle, Ban } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { commandsApi, type SourceQueueJob } from '@/lib/api/commands'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { cn } from '@/lib/utils'

type QueueFilter = 'all' | 'active' | 'failed' | 'completed' | 'canceled'

const ACTIVE_STATUSES = new Set(['new', 'queued', 'running'])

function getStatusPresentation(status: string, t: ReturnType<typeof useTranslation>['t']) {
  switch (status) {
    case 'new':
    case 'queued':
      return {
        label: t.sources.statusQueued,
        icon: Clock3,
        className: 'bg-blue-50 text-blue-700 border-blue-200',
      }
    case 'running':
      return {
        label: t.sources.statusProcessing,
        icon: Loader2,
        className: 'bg-amber-50 text-amber-700 border-amber-200',
      }
    case 'completed':
      return {
        label: t.sources.statusCompleted,
        icon: CheckCircle2,
        className: 'bg-green-50 text-green-700 border-green-200',
      }
    case 'failed':
      return {
        label: t.sources.statusFailed,
        icon: AlertTriangle,
        className: 'bg-red-50 text-red-700 border-red-200',
      }
    case 'canceled':
      return {
        label: t.sources.statusCanceled,
        icon: Ban,
        className: 'bg-zinc-100 text-zinc-700 border-zinc-300',
      }
    default:
      return {
        label: status,
        icon: Clock3,
        className: 'bg-muted text-muted-foreground border-border',
      }
  }
}

function filterJobs(jobs: SourceQueueJob[], filter: QueueFilter) {
  switch (filter) {
    case 'active':
      return jobs.filter((job) => ACTIVE_STATUSES.has(job.status))
    case 'failed':
      return jobs.filter((job) => job.status === 'failed')
    case 'completed':
      return jobs.filter((job) => job.status === 'completed')
    case 'canceled':
      return jobs.filter((job) => job.status === 'canceled')
    default:
      return jobs
  }
}

export function SourceQueue() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<QueueFilter>('active')
  const [jobToCancel, setJobToCancel] = useState<SourceQueueJob | null>(null)

  const query = useQuery({
    queryKey: QUERY_KEYS.sourceQueue,
    queryFn: () => commandsApi.listSourceQueue(undefined, 100),
    refetchInterval: (currentQuery) => {
      const jobs = (currentQuery.state.data ?? []) as SourceQueueJob[]
      return jobs.some((job) => ACTIVE_STATUSES.has(job.status)) ? 4000 : false
    },
    staleTime: 0,
  })

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => commandsApi.cancelJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceQueue })
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      toast({
        title: t.common.success,
        description: t.advanced.sourceQueue.cancelSuccess,
      })
      setJobToCancel(null)
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error, (key) => t(key), t.advanced.sourceQueue.cancelFailed),
        variant: 'destructive',
      })
    },
  })

  const jobs = query.data ?? []
  const filteredJobs = useMemo(() => filterJobs(jobs, filter), [jobs, filter])
  const activeCount = jobs.filter((job) => ACTIVE_STATUSES.has(job.status)).length

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle>{t.advanced.sourceQueue.title}</CardTitle>
              <CardDescription>{t.advanced.sourceQueue.desc}</CardDescription>
            </div>

            <div className="flex items-center gap-2">
              <Badge variant="outline">
                {t.advanced.sourceQueue.activeCount.replace('{count}', activeCount.toString())}
              </Badge>
              <Button
                variant="outline"
                size="sm"
                onClick={() => query.refetch()}
                disabled={query.isFetching}
              >
                {query.isFetching ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                {t.common.refresh}
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <Select value={filter} onValueChange={(value) => setFilter(value as QueueFilter)}>
              <SelectTrigger className="w-full md:w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t.advanced.sourceQueue.filters.all}</SelectItem>
                <SelectItem value="active">{t.advanced.sourceQueue.filters.active}</SelectItem>
                <SelectItem value="failed">{t.advanced.sourceQueue.filters.failed}</SelectItem>
                <SelectItem value="completed">{t.advanced.sourceQueue.filters.completed}</SelectItem>
                <SelectItem value="canceled">{t.advanced.sourceQueue.filters.canceled}</SelectItem>
              </SelectContent>
            </Select>

            <p className="text-sm text-muted-foreground">
              {t.advanced.sourceQueue.pollingHint}
            </p>
          </div>

          {query.isError && (
            <Alert variant="destructive">
              <CircleX className="h-4 w-4" />
              <AlertDescription>
                {getApiErrorMessage(query.error, (key) => t(key), t.advanced.sourceQueue.loadFailed)}
              </AlertDescription>
            </Alert>
          )}

          {query.isLoading ? (
            <div className="flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t.common.loading}
            </div>
          ) : filteredJobs.length === 0 ? (
            <div className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
              {t.advanced.sourceQueue.empty}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredJobs.map((job) => {
                const status = getStatusPresentation(job.status, t)
                const StatusIcon = status.icon

                return (
                  <div
                    key={job.job_id}
                    className="rounded-lg border bg-card px-4 py-3 shadow-sm"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className={cn('gap-1.5', status.className)}>
                            <StatusIcon className={cn('h-3.5 w-3.5', job.status === 'running' && 'animate-spin')} />
                            {status.label}
                          </Badge>
                          <Badge variant="secondary">{job.command || 'process_source'}</Badge>
                        </div>

                        <div className="space-y-1">
                          <p className="font-medium break-all">
                            {job.source_title || job.source_path || job.source_id || job.job_id}
                          </p>
                          {job.source_path && (
                            <p className="font-mono text-xs text-muted-foreground break-all">
                              {job.source_path}
                            </p>
                          )}
                        </div>

                        <div className="grid gap-1 text-sm text-muted-foreground md:grid-cols-2">
                          <p>{t.sources.id}: {job.source_id || '—'}</p>
                          <p>{t.advanced.sourceQueue.jobId}: {job.job_id}</p>
                          <p>{t.common.created_label}: {job.created ? new Date(job.created).toLocaleString() : '—'}</p>
                          <p>{t.common.updated_label}: {job.updated ? new Date(job.updated).toLocaleString() : '—'}</p>
                        </div>

                        {job.error_message && (
                          <Alert variant="destructive" className="mt-2">
                            <AlertTriangle className="h-4 w-4" />
                            <AlertDescription>{job.error_message}</AlertDescription>
                          </Alert>
                        )}
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => query.refetch()}
                          disabled={query.isFetching}
                        >
                          <RefreshCw className="mr-2 h-4 w-4" />
                          {t.common.refresh}
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={!job.can_cancel || cancelMutation.isPending}
                          onClick={() => setJobToCancel(job)}
                        >
                          {cancelMutation.isPending && jobToCancel?.job_id === job.job_id ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Ban className="mr-2 h-4 w-4" />
                          )}
                          {t.common.cancel}
                        </Button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!jobToCancel}
        onOpenChange={(open) => !open && setJobToCancel(null)}
        title={t.advanced.sourceQueue.cancelTitle}
        description={(jobToCancel?.source_title || jobToCancel?.source_path)
          ? t.advanced.sourceQueue.cancelDesc.replace(
              '{name}',
              jobToCancel.source_title || jobToCancel.source_path || jobToCancel.job_id,
            )
          : t.advanced.sourceQueue.cancelDescGeneric}
        confirmText={t.common.cancel}
        confirmVariant="destructive"
        onConfirm={() => {
          if (jobToCancel) {
            cancelMutation.mutate(jobToCancel.job_id)
          }
        }}
        isLoading={cancelMutation.isPending}
      />
    </>
  )
}
