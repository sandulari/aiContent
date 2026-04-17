import { ReactNode } from "react";
import clsx from "clsx";

interface CardProps { title?: string; children: ReactNode; className?: string; }

export function Card({ title, children, className }: CardProps) {
  return (
    <div className={clsx("bg-[#161b22] border border-[#21262d] rounded-2xl p-6", className)}>
      {title && <h3 className="text-[10px] font-semibold text-[#484f58] uppercase tracking-[0.15em] mb-4">{title}</h3>}
      {children}
    </div>
  );
}
