import { ReactNode } from "react";
import clsx from "clsx";

interface CardProps { title?: string; children: ReactNode; className?: string; }

export function Card({ title, children, className }: CardProps) {
  return (
    <div className={clsx("bg-[#0d1117]/80 backdrop-blur-sm border border-[#1b2028] rounded-2xl p-6 card-glow", className)}>
      {title && <h3 className="text-[10px] font-semibold text-[#484f58] uppercase tracking-[0.15em] mb-4">{title}</h3>}
      {children}
    </div>
  );
}
