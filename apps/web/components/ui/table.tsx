import { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import clsx from "clsx";

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("overflow-x-auto", className)}><table className="w-full">{children}</table></div>;
}
export function TableHead({ children }: { children: ReactNode }) {
  return <thead><tr className="border-b border-[#21262d]">{children}</tr></thead>;
}
export function TableBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-[#21262d]/50">{children}</tbody>;
}
export function TableRow({ children, className, onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  return <tr className={clsx("hover:bg-[#161b22]/60 transition-colors", onClick && "cursor-pointer", className)} onClick={onClick}>{children}</tr>;
}
export function TableCell({ children, className, ...props }: TdHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return <td className={clsx("px-4 py-3 text-sm text-[#e6edf3]", className)} {...props}>{children}</td>;
}
export function TableHeaderCell({ children, className, ...props }: ThHTMLAttributes<HTMLTableHeaderCellElement> & { children?: ReactNode }) {
  return <th className={clsx("px-4 py-2.5 text-left text-[10px] font-medium text-[#484f58] uppercase tracking-wider", className)} {...props}>{children}</th>;
}
