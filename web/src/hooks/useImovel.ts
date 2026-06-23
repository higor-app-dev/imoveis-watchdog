"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/fetcher";
import type { ImovelData } from "@/components/ImovelCard";

export function useImovel(id: string) {
  const { data, error, isLoading, mutate } = useSWR<ImovelData>(
    id ? `/api/imoveis/${encodeURIComponent(id)}` : null,
    fetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
    }
  );

  return {
    imovel: data ?? null,
    loading: isLoading,
    error: error ? (error instanceof Error ? error.message : "Erro ao carregar") : null,
    mutate,
  };
}
