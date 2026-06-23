"use client";

import { useEffect, useRef } from "react";

interface InfiniteScrollProps {
  /** Called when the sentinel enters the viewport */
  onLoadMore: () => void;
  /** Whether there are more results to load */
  hasMore: boolean;
  /** Whether a load is in progress */
  loading: boolean;
  /** Optional root margin (default: "200px") */
  rootMargin?: string;
}

/**
 * Renders a sentinel div at the bottom that triggers `onLoadMore`
 * when scrolled into view. Uses IntersectionObserver with no deps.
 */
export default function InfiniteScroll({
  onLoadMore,
  hasMore,
  loading,
  rootMargin = "200px",
}: InfiniteScrollProps) {
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasMore) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasMore && !loading) {
          onLoadMore();
        }
      },
      { rootMargin }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loading, onLoadMore, rootMargin]);

  if (!hasMore) return null;

  return (
    <div ref={sentinelRef} className="flex items-center justify-center py-6">
      {loading && (
        <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <span className="inline-block size-4 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--primary)]" />
          Carregando mais imóveis...
        </div>
      )}
    </div>
  );
}
