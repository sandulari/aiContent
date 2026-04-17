"use client";
import { Button } from "@/components/ui/button";

interface EmptyStateProps { title: string; description?: string; actionLabel?: string; onAction?: () => void; icon?: React.ReactNode; }

export function EmptyState({ title, description, actionLabel, onAction, icon }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      {icon || (
        <svg className="w-10 h-10 text-[#21262d] mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      )}
      <h3 className="text-sm font-medium text-[#e6edf3] mb-1">{title}</h3>
      {description && <p className="text-xs text-[#484f58] mb-4 max-w-xs text-center">{description}</p>}
      {actionLabel && onAction && <Button size="sm" onClick={onAction}>{actionLabel}</Button>}
    </div>
  );
}
