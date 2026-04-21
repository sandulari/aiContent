"use client";

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-lg skeleton-shimmer ${className}`}
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
    <div className="min-h-screen bg-[#0d1117]">
      <div className="p-6 max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Skeleton className="h-7 w-32" />
            <Skeleton className="h-6 w-20 rounded-md" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-36 rounded-lg" />
            <Skeleton className="h-9 w-32 rounded-lg" />
            <Skeleton className="h-9 w-9 rounded-lg" />
          </div>
        </div>

        {/* Primary stat cards — 4 columns */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-[#161b22] border border-[#21262d] rounded-xl p-5 space-y-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-8 w-20" />
              <Skeleton className="h-3 w-28" />
            </div>
          ))}
        </div>

        {/* Secondary stat cards — 3 columns */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-[#161b22] border border-[#21262d] rounded-xl p-5 space-y-3">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-3 w-24" />
            </div>
          ))}
        </div>

        {/* Top Performing Reel */}
        <div>
          <Skeleton className="h-4 w-40 mb-3" />
          <div className="bg-[#161b22] border border-[#21262d] rounded-xl p-5 space-y-3">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <div className="flex gap-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
        </div>

        {/* Reels Table */}
        <div>
          <Skeleton className="h-4 w-36 mb-3" />
          <div className="bg-[#161b22] border border-[#21262d] rounded-xl overflow-hidden">
            {/* Table header */}
            <div className="flex gap-4 px-4 py-2.5 border-b border-[#21262d]">
              <Skeleton className="h-3 w-32 flex-1" />
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-3 w-14" />
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-3 w-20" />
            </div>
            {/* Table rows */}
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="flex gap-4 px-4 py-3 items-center border-b border-[#21262d]/50 last:border-0">
                <Skeleton className={`h-3.5 ${i === 0 ? "w-full" : i === 1 ? "w-5/6" : i === 2 ? "w-4/5" : i === 3 ? "w-3/4" : i === 4 ? "w-2/3" : "w-3/5"}`} />
                <Skeleton className="h-3 w-14" />
                <Skeleton className="h-3 w-12" />
                <Skeleton className="h-3 w-12" />
                <Skeleton className="h-3 w-16" />
              </div>
            ))}
          </div>
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

export function SkeletonEditor() {
  return (
    <div className="flex h-screen bg-[#0d1117]">
      <div className="w-56 border-r border-[#21262d] p-3 space-y-2">
        <Skeleton className="h-5 w-20 mb-4" />
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-9 w-full rounded-lg" />
        ))}
      </div>
      <div className="flex-1 flex items-center justify-center">
        <Skeleton className="w-[360px] h-[640px] rounded-xl" />
      </div>
      <div className="w-72 border-l border-[#21262d] p-3 space-y-4">
        <Skeleton className="h-5 w-24" />
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-8 w-full rounded-lg" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonReelDetail() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <Skeleton className="h-4 w-16" />
      <div className="bg-[#161b22] border border-[#21262d] rounded-2xl p-6 space-y-4">
        <div className="flex items-start justify-between">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-3/5" />
          </div>
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
        <div className="flex gap-4">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
      <div className="bg-[#161b22] border border-[#21262d] rounded-2xl p-6 space-y-3">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-3 w-64" />
        <div className="flex items-center gap-3 bg-[#0d1117] rounded-lg p-3">
          <Skeleton className="w-32 h-20 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-3 w-24" />
          </div>
          <Skeleton className="h-8 w-24 rounded-lg" />
        </div>
      </div>
      <div className="space-y-3">
        <Skeleton className="h-4 w-32" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 bg-[#161b22] border border-[#21262d] rounded-lg p-3">
            <Skeleton className="w-20 h-14 rounded" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-48" />
              <Skeleton className="h-2.5 w-20" />
            </div>
            <Skeleton className="h-7 w-16 rounded-lg" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonExports() {
  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <div>
        <Skeleton className="h-7 w-36" />
        <Skeleton className="h-3.5 w-52 mt-2" />
      </div>
      <SkeletonTable rows={6} />
    </div>
  );
}

export function SkeletonLibrary() {
  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-3.5 w-48 mt-2" />
        </div>
        <Skeleton className="h-9 w-32 rounded-lg" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    </div>
  );
}
