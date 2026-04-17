"use client";

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-lg bg-gradient-to-r from-[#161b22] via-[#1c2129] to-[#161b22] bg-[length:200%_100%] ${className}`}
      style={{ animationDuration: '1.8s' }}
    />
  );
}

export function SkeletonText({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2.5 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-3.5 ${i === lines - 1 ? 'w-3/5' : i === 0 ? 'w-full' : 'w-4/5'}`}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`bg-[#161b22] border border-[#21262d] rounded-2xl p-6 space-y-4 ${className}`}>
      <Skeleton className="h-5 w-2/3" />
      <SkeletonText lines={2} />
      <div className="flex gap-2 pt-2">
        <Skeleton className="h-8 w-20 rounded-lg" />
        <Skeleton className="h-8 w-20 rounded-lg" />
      </div>
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="bg-[#161b22] border border-[#21262d] rounded-2xl overflow-hidden">
      <div className="border-b border-[#21262d] px-4 py-3 flex gap-6">
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-24" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="px-4 py-3.5 flex gap-6 items-center border-b border-[#21262d]/50 last:border-0">
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-48" />
            <Skeleton className="h-2.5 w-32" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-16 rounded-lg" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonDashboard() {
  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <Skeleton className="h-7 w-48" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1,2,3,4].map(i => (
          <div key={i} className="bg-[#161b22] border border-[#21262d] rounded-2xl p-5 space-y-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-2.5 w-16" />
          </div>
        ))}
      </div>
      <div className="bg-[#161b22] border border-[#21262d] rounded-2xl p-6 space-y-4">
        <Skeleton className="h-5 w-32" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1,2,3].map(i => <SkeletonCard key={i} />)}
        </div>
      </div>
    </div>
  );
}

export function SkeletonDiscover() {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex justify-between items-center">
        <Skeleton className="h-7 w-32" />
        <div className="flex gap-2">
          <Skeleton className="h-9 w-32 rounded-lg" />
          <Skeleton className="h-9 w-32 rounded-lg" />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="bg-[#161b22] border border-[#21262d] rounded-2xl overflow-hidden">
            <Skeleton className="h-48 w-full rounded-none" />
            <div className="p-4 space-y-3">
              <div className="flex justify-between">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-5 w-12 rounded-full" />
              </div>
              <SkeletonText lines={2} />
              <div className="flex gap-2">
                <Skeleton className="h-8 flex-1 rounded-lg" />
                <Skeleton className="h-8 w-8 rounded-lg" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonSettings() {
  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8">
      <div>
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-3.5 w-64 mt-2" />
      </div>
      <div className="bg-[#161b22] border border-[#21262d] rounded-2xl p-6 space-y-4">
        <Skeleton className="h-5 w-40" />
        <div className="flex gap-2">
          <Skeleton className="h-10 w-32 rounded-lg" />
          <Skeleton className="h-10 flex-1 rounded-lg" />
          <Skeleton className="h-10 w-24 rounded-lg" />
        </div>
      </div>
      {[1,2].map(i => (
        <div key={i} className="bg-[#161b22] border border-[#21262d] rounded-2xl p-6 space-y-3">
          <Skeleton className="h-4 w-32" />
          {[1,2].map(j => (
            <div key={j} className="flex justify-between items-center p-3 bg-[#0d1117] rounded-lg">
              <div className="space-y-1">
                <Skeleton className="h-3.5 w-32" />
                <Skeleton className="h-2.5 w-48" />
              </div>
              <Skeleton className="h-8 w-20 rounded-lg" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
