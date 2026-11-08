import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function ErrorCard({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-12 text-center h-full min-h-[200px] bg-background border border-border rounded-xl">
      <AlertTriangle className="h-8 w-8 text-destructive opacity-80" />
      <p className="text-sm text-muted-foreground max-w-md">{message || 'An error occurred while fetching data.'}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-2">
          Retry
        </Button>
      )}
    </div>
  )
}
