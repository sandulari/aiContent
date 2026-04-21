"use client";

import { ReactNode, useEffect } from "react";
import clsx from "clsx";

interface ModalProps { isOpen: boolean; onClose: () => void; title?: string; children: ReactNode; className?: string; }

export function Modal({ isOpen, onClose, title, children, className }: ModalProps) {
  useEffect(() => {
    if (!isOpen) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", h);
    return () => { document.removeEventListener("keydown", h); };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className={clsx("relative z-10 w-full max-w-md bg-[#161b22] border border-[#21262d] rounded-lg shadow-[0_2px_8px_rgba(0,0,0,0.1)]", className)}>
        {title && (
          <div className="flex items-center justify-between px-5 py-4 border-b border-[#21262d]">
            <h2 className="text-base font-semibold text-[#e6edf3]">{title}</h2>
            <button onClick={onClose} className="text-[#484f58] hover:text-[#e6edf3] transition-colors">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>
        )}
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
