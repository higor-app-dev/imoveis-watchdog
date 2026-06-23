"use client";

import useSWRInfinite from "swr/infinite";
import { fetcher } from "@/lib/fetcher";
import { useMemo, useCallback } from "react";
import type { ImovelData } from "@/components/ImovelCard";

interface UseImovelScrollOptions {
  /** Base URL for the API endpoint */
  baseUrl: string;
  /** Number of items per batch */
  perPage?: number;
  /** Additional query params (sort, order, etc.) to include in every request */
  extraParams?: Record<string, string>;
}

interface UseImovelScrollReturn {
  /** Accumulated imoveis */
  imoveis: ImovelData[];
  /** Total available (from the API) */
  total: number;
  /** Whether initial load is in progress */
  loading: boolean;
  /** Whether a "load more" is in progress */
  loadingMore: boolean;
  /** Whether all results have been loaded */
  hasMore: boolean;
  /** Error message, if any */
  error: string | null;
  /** Reset and reload from scratch (e.g., on sort/filter change) */
  reset: () => void;
  /** Load the next batch */
  loadMore: () => void;
}

const PAGE_SIZE = 24;

export function useImovelScroll({
  baseUrl,
  perPage = PAGE_SIZE,
  extraParams = {},
}: UseImovelScrollOptions): UseImovelScrollReturn {
  // Stable key for the extra params — JSON stringified so useSWRInfinite re-creates
  // the fetcher when params change (which triggers a reset)
  const paramsKey = useMemo(() => JSON.stringify(extraParams), [extraParams]);

  const getKey = useCallback(
    (pageIndex: number, previousPageData: { imoveis: ImovelData[] } | null) => {
      // reached the end
      if (previousPageData && previousPageData.imoveis.length === 0) return null;
      // first page
      const offset = pageIndex * perPage;
      const q = new URLSearchParams();
      q.set("limit", String(perPage));
      q.set("offset", String(offset));
      for (const [k, v] of Object.entries(extraParams)) {
        if (v) q.set(k, v);
      }
      // Include paramsKey as a cache-busting signal so SWR treats changes as a new key
      const url = `${baseUrl}?${q}`;
      return `${url}&_key=${paramsKey}`;
    },
    [baseUrl, perPage, extraParams, paramsKey]
  );

  const { data, error, isLoading, isValidating, setSize, size, mutate } =
    useSWRInfinite<{ imoveis: ImovelData[]; total: number }>(
      getKey,
      fetcher,
      {
        revalidateFirstPage: false,
        revalidateOnFocus: false,
        revalidateOnReconnect: false,
        dedupingInterval: 5_000,
      }
    );

  // Flatten all pages into one array
  const imoveis = useMemo(
    () => (data ? data.flatMap((page) => page.imoveis) : []),
    [data]
  );

  // Total from first page
  const total = data?.[0]?.total ?? 0;

  // Determine if there are more pages to load
  const hasMore = imoveis.length < total;

  // "loadingMore" = currently fetching a page that is NOT the first one
  const loadingMore = isValidating && size > 0 && imoveis.length > 0;

  const loadMore = useCallback(() => {
    if (!hasMore || isValidating) return;
    setSize((s) => s + 1);
  }, [hasMore, isValidating, setSize]);

  const reset = useCallback(() => {
    mutate(undefined, { revalidate: false });
    setSize(1);
  }, [mutate, setSize]);

  return {
    imoveis,
    total,
    loading: isLoading,
    loadingMore,
    hasMore,
    error: error ? (error instanceof Error ? error.message : "Erro ao carregar") : null,
    reset,
    loadMore,
  };
}
