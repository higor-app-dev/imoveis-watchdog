"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { X } from "lucide-react";

interface ProviderFilterProps {
  /** Current list of selected providers (from URL params) */
  selected: string[];
  /** Called when selection changes */
  onChange: (fontes: string[]) => void;
  /** Optional busca ID — when set, only shows fontes available in that busca */
  buscaId?: number;
}

export default function ProviderFilter({ selected, onChange, buscaId }: ProviderFilterProps) {
  const [allFontes, setAllFontes] = useState<string[]>([]);
  const [loadingFontes, setLoadingFontes] = useState(true);

  useEffect(() => {
    setLoadingFontes(true);
    const url = buscaId
      ? `/api/imoveis/fontes?busca_id=${buscaId}`
      : "/api/imoveis/fontes";
    fetch(url)
      .then((r) => r.json())
      .then((data: string[]) => setAllFontes(data))
      .catch(console.error)
      .finally(() => setLoadingFontes(false));
  }, [buscaId]);

  const toggleFonte = useCallback(
    (fonte: string) => {
      const next = selected.includes(fonte)
        ? selected.filter((f) => f !== fonte)
        : [...selected, fonte];
      onChange(next);
    },
    [selected, onChange]
  );

  if (loadingFontes || allFontes.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-[var(--muted-foreground)] font-medium shrink-0">
        Fontes
      </span>
      {allFontes.map((fonte) => {
        const isActive = selected.includes(fonte);
        return (
          <button
            key={fonte}
            onClick={() => toggleFonte(fonte)}
            className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium border transition-all ${
              isActive
                ? "bg-[var(--primary)] text-[var(--primary-foreground)] border-[var(--primary)]"
                : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
            }`}
          >
            {fonte}
            {isActive && <X className="size-3" />}
          </button>
        );
      })}
      {selected.length > 0 && selected.length < allFontes.length && (
        <button
          onClick={() => onChange([])}
          className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] underline transition-colors"
        >
          Limpar filtros
        </button>
      )}
    </div>
  );
}
