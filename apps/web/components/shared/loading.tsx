"use client";
import clsx from "clsx";

const sizes = { sm: "w-4 h-4 border-[1.5px]", md: "w-5 h-5 border-2", lg: "w-7 h-7 border-2" };

export function Loading({ size = "md", className }: { size?: "sm" | "md" | "lg"; className?: string }) {
  return (
    <div className={clsx("flex items-center justify-center", className)}>
      <div className={clsx("rounded-full border-[#58a6ff] border-t-transparent animate-spin", sizes[size])} />
    </div>
  );
}
