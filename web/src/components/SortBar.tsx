"use client";

import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";

export type SortField = "data" | "preco" | "area";
export type SortOrder = "asc" | "desc";

interface SortOption {
  value: SortField;
  label: string;
}

const OPTIONS: SortOption[] = [
  { value: "data", label: "Data de descoberta" },
  { value: "preco", label: "Valor" },
  { value: "area", label: "Área (m²)" },
];

interface SortBarProps {
  sort: SortField;
  order: SortOrder;
  onChange: (sort: SortField, order: SortOrder) => void;
}

export default function SortBar({ sort, order, onChange }: SortBarProps) {
  function toggleOrder() {
    onChange(sort, order === "asc" ? "desc" : "asc");
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-[var(--muted-foreground)] font-medium">
        Ordenar por
      </span>
      <div className="flex gap-1">
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value, opt.value === sort ? order : "desc")}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
              sort === opt.value
                ? "bg-[var(--primary)] text-[var(--primary-foreground)] border-[var(--primary)]"
                : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <button
        onClick={toggleOrder}
        className="flex items-center gap-1 px-2 py-1.5 text-xs rounded-lg border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)] transition-colors"
        title={order === "asc" ? "Crescente" : "Decrescente"}
      >
        {order === "asc" ? (
          <ArrowUp className="size-3.5" />
        ) : (
          <ArrowDown className="size-3.5" />
        )}
        <span className="hidden sm:inline">
          {order === "asc" ? "Crescente" : "Decrescente"}
        </span>
      </button>
    </div>
  );
}
