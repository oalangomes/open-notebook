"use client"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { ScrollArea } from "@/components/ui/scroll-area"

interface GitSourcePreviewItem {
  path: string
  source_type: 'explicit' | 'seed' | 'discovered'
  discovered_from?: string | null
  file_type?: string | null
}

interface GitSourcePreviewStepProps {
  items: GitSourcePreviewItem[]
  selectedPaths: string[]
  warnings?: string[]
  isPortuguese?: boolean
  onTogglePath: (path: string) => void
  onSelectAll: () => void
  onClearSelection: () => void
}

function getSourceTypeLabel(sourceType: GitSourcePreviewItem['source_type'], isPortuguese: boolean) {
  if (sourceType === 'explicit') {
    return isPortuguese ? 'Explícito' : 'Explicit'
  }
  if (sourceType === 'seed') {
    return isPortuguese ? 'Seed' : 'Seed'
  }
  return isPortuguese ? 'Descoberto' : 'Discovered'
}

export function GitSourcePreviewStep({
  items,
  selectedPaths,
  warnings = [],
  isPortuguese = false,
  onTogglePath,
  onSelectAll,
  onClearSelection,
}: GitSourcePreviewStepProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 rounded-lg border border-border bg-muted/30 p-4">
        <div className="space-y-1">
          <h3 className="text-sm font-medium">
            {isPortuguese ? 'Confirme os arquivos antes de importar' : 'Confirm the files before importing'}
          </h3>
          <p className="text-sm text-muted-foreground">
            {isPortuguese
              ? 'Revise os arquivos identificados pelo repositório e mantenha marcados apenas os que devem virar fontes.'
              : 'Review the files identified from the repository and keep checked only the ones that should become sources.'}
          </p>
          <p className="text-xs text-muted-foreground">
            {isPortuguese
              ? `${selectedPaths.length} de ${items.length} arquivo(s) selecionado(s).`
              : `${selectedPaths.length} of ${items.length} file(s) selected.`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onSelectAll}>
            {isPortuguese ? 'Selecionar todos' : 'Select all'}
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onClearSelection}>
            {isPortuguese ? 'Limpar seleção' : 'Clear selection'}
          </Button>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-medium">
            {isPortuguese ? 'Avisos da descoberta' : 'Discovery warnings'}
          </p>
          <ul className="mt-2 space-y-1">
            {warnings.map((warning, index) => (
              <li key={`${warning}-${index}`} className="text-xs">
                {warning}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ScrollArea className="h-[340px] rounded-lg border">
        <div className="divide-y">
          {items.map((item) => {
            const checked = selectedPaths.includes(item.path)
            return (
              <label
                key={item.path}
                className="flex cursor-pointer items-start gap-3 p-4 transition-colors hover:bg-muted/40"
              >
                <Checkbox
                  checked={checked}
                  onCheckedChange={() => onTogglePath(item.path)}
                  className="mt-0.5"
                />
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-mono text-sm">{item.path}</span>
                    <Badge variant="secondary" className="text-[10px] uppercase tracking-wide">
                      {getSourceTypeLabel(item.source_type, isPortuguese)}
                    </Badge>
                    {item.file_type && (
                      <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
                        .{item.file_type}
                      </Badge>
                    )}
                  </div>
                  {item.discovered_from && (
                    <p className="text-xs text-muted-foreground">
                      {isPortuguese ? 'Descoberto via' : 'Discovered via'} {item.discovered_from}
                    </p>
                  )}
                </div>
              </label>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}
