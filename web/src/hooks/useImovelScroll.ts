"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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

export function useImovelScroll({
  baseUrl,
  perPage = 20,
  extraParams = {},
}: UseImovelScrollOptions): UseImovelScrollReturn {
  const [imoveis, setImoveis] = useState<ImovelData[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const offsetRef = useRef(0);
  const hasMoreRef = useRef(true);
  const mountedRef = useRef(true);
  const keyRef = useRef(0); // increments on reset to cancel stale requests

  const buildUrl = useCallback(
    (offset: number) => {
      const q = new URLSearchParams();
      q.set("limit", String(perPage));
      q.set("offset", String(offset));
      for (const [k, v] of Object.entries(extraParams)) {
        if (v) q.set(k, v);
      }
      return `${baseUrl}?${q}`;
    },
    [baseUrl, perPage, extraParams]
  );

  const fetchPage = useCallback(
    async (offset: number, append: boolean, key: number) => {
      try {
        const res = await fetch(buildUrl(offset));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!mountedRef.current || key !== keyRef.current) return;

        const items: ImovelData[] = data.imoveis ?? data ?? [];
        const totalCount = data.total ?? items.length;

        if (append) {
          setImoveis((prev) => [...prev, ...items]);
        } else {
          setImoveis(items);
        }
        setTotal(totalCount);
        hasMoreRef.current = offset + perPage < totalCount;
        offsetRef.current = offset + perPage;
      } catch (err) {
        if (mountedRef.current && key === keyRef.current) {
          setError(err instanceof Error ? err.message : "Erro ao carregar");
        }
      }
    },
    [buildUrl, perPage]
  );

  // Initial load
  useEffect(() => {
    mountedRef.current = true;
    keyRef.current += 1;
    const key = keyRef.current;
    setLoading(true);
    setError(null);
    fetchPage(0, false, key).finally(() => {
      if (mountedRef.current && key === keyRef.current) {
        setLoading(false);
      }
    });
    return () => {
      mountedRef.current = false;
    };
  }, [fetchPage]);

  const loadMore = useCallback(() => {
    if (!hasMoreRef.current || loadingMore) return;
    setLoadingMore(true);
    const key = keyRef.current;
    fetchPage(offsetRef.current, true, key).finally(() => {
      if (mountedRef.current && key === keyRef.current) {
        setLoadingMore(false);
      }
    });
  }, [fetchPage, loadingMore]);

  const reset = useCallback(() => {
    keyRef.current += 1;
    const key = keyRef.current;
    offsetRef.current = 0;
    hasMoreRef.current = true;
    setImoveis([]);
    setLoading(true);
    setError(null);
    fetchPage(0, false, key).finally(() => {
      if (mountedRef.current && key === keyRef.current) {
        setLoading(false);
      }
    });
  }, [fetchPage]);

  const hasMore = hasMoreRef.current && offsetRef.current < total;

  return {
    imoveis,
    total,
    loading,
    loadingMore,
    hasMore,
    error,
    reset,
    loadMore,
  };
}
