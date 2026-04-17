"use client";
import clsx from "clsx";

const colors: Record<string, string> = {
  discovered: "bg-[#1a1a1a] text-[#555]",
  pending: "bg-[#1a1a1a] text-[#555]",
  queued: "bg-[#0a1a2e] text-[#4a9eff]",
  searching_source: "bg-[#0a1a2e] text-[#4a9eff]",
  source_found: "bg-[#0a1a2e] text-[#6ab4ff]",
  downloading: "bg-[#1a1500] text-[#eab308]",
  running: "bg-[#1a1500] text-[#eab308]",
  downloaded: "bg-[#0a1a0a] text-[#4ade80]",
  done: "bg-[#0a1a0a] text-[#4ade80]",
  success: "bg-[#0a1a0a] text-[#4ade80]",
  completed: "bg-[#0a1a0a] text-[#4ade80]",
  failed: "bg-[#1a0a0a] text-[#f87171]",
  editing: "bg-[#150a1a] text-[#c084fc]",
  exporting: "bg-[#1a1500] text-[#fb923c]",
};

export function Badge({ status, className }: { status: string; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider", colors[status] || colors.pending, className)}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
