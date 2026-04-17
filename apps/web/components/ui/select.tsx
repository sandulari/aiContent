"use client";

import clsx from "clsx";

interface SelectProps {
  label?: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export function Select({ label, options, value, onChange, placeholder, className }: SelectProps) {
  return (
    <div>
      {label && <label className="block text-xs font-medium text-[#7d8590] mb-1.5">{label}</label>}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={clsx(
          "w-full h-9 px-3 text-sm bg-[#0d1117] text-[#e6edf3] border border-[#21262d] rounded-lg",
          "focus:outline-none focus:border-[#58a6ff] transition-colors duration-150 appearance-none cursor-pointer",
          "bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%2212%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%237d8590%22%20stroke-width%3D%222%22%3E%3Cpath%20d%3D%22M6%209l6%206%206-6%22%2F%3E%3C%2Fsvg%3E')] bg-no-repeat bg-[right_10px_center]",
          className
        )}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}
