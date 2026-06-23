"use client";

import { Suspense, useState, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Search,
} from "lucide-react";
import { ImovelCard } from "@/components/ImovelCard";
import type { ImovelData } from "@/components/ImovelCard";
import SortBar from "@/components/SortBar";
import type { SortField, SortOrder } from "@/components/SortBar";
import InfiniteScroll from "@/components/InfiniteScroll";
import ProviderFilter from "@/components/ProviderFilter";
import { useImovelScroll } from "@/hooks/useImovelScroll";

function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex items-center justify-center py-20">
        <div className="animate-pulse text-[var(--muted-foreground)]">Carregando...</div>
      </div>
    </div>
  );
}

function ImoveisContent() {
  const sp = useSearchParams();
  const router = useRouter();

  const [searchTerm, setSearchTerm] = useState(sp.get("bairro") || "");

  const sort = (sp.get("sort") as SortField) || "data";
  const order = (sp.get("order") as SortOrder) || "desc";
  const fontesRaw = sp.get("fontes") || "";
  const fontes = useMemo(
    () => fontesRaw.split(",").map((f) => f.trim()).filter(Boolean),
    [fontesRaw]
  );

  const extraParams = useMemo(() => {
    const params: Record<string, string> = {
      sort,
      order,
      fontes: fontes.length > 0 ? fontes.join(",") : "",
    };
    if (searchTerm) params.bairro = searchTerm;
    return params;
  }, [sort, order, fontes, searchTerm]);

  const { imoveis, total, loading, loadingMore, hasMore, error, loadMore } =
    useImovelScroll({ baseUrl: "/api/imoveis", perPage: 24, extraParams });

  function handleSortChange(newSort: SortField, newOrder: SortOrder) {
    const q = new URLSearchParams(sp.toString());
    q.set("sort", newSort);
    q.set("order", newOrder);
    router.replace(`/imoveis?${q}`, { scroll: false });
  }

  function handleFontesChange(newFontes: string[]) {
    const q = new URLSearchParams(sp.toString());
    if (newFontes.length > 0) {
      q.set("fontes", newFontes.join(","));
    } else {
      q.delete("fontes");
    }
    router.replace(`/imoveis?${q}`, { scroll: false });
  }

  function handleSearch(value: string) {
    setSearchTerm(value);
  }

  if (loading && imoveis.length === 0) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="flex items-center justify-center py-20">
          <div className="animate-pulse text-[var(--muted-foreground)]">Buscando imóveis...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="rounded-xl border border-red-300 bg-red-50 dark:bg-red-950 dark:border-red-800 p-6 text-center text-sm text-red-700 dark:text-red-300">
          Erro ao carregar: {error}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3 min-w-0">
          <Link href="/" className="shrink-0 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
            <ArrowLeft className="size-5" />
          </Link>
          <div className="min-w-0">
            <h1 className="text-xl font-bold">Explorar Imóveis</h1>
            <p className="text-sm text-[var(--muted-foreground)]">
              {total} imóveis encontrados
              {!hasMore && total > 24 && " · Todos carregados"}
            </p>
          </div>
        </div>
      </div>

      <div className="mb-4 flex flex-col sm:flex-row gap-3">
        <div className="relative max-w-md flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[var(--muted-foreground)]" />
          <input
            type="text"
            placeholder="Buscar por bairro..."
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
            className="w-full rounded-xl border border-[var(--border)] bg-[var(--background)] pl-9 pr-4 py-2.5 text-sm outline-none focus:border-[var(--primary)] transition-colors"
          />
        </div>
        <SortBar sort={sort} order={order} onChange={handleSortChange} />
      </div>

      <div className="mb-4">
        <ProviderFilter selected={fontes} onChange={handleFontesChange} />
      </div>

      {imoveis.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
          {searchTerm ? "Nenhum imóvel encontrado nesse bairro." : "Nenhum imóvel cadastrado."}
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {imoveis.map((i) => (
              <ImovelCard key={i.id} imovel={i} />
            ))}
          </div>

          {!hasMore && total > 24 && (
            <p className="text-center text-xs text-[var(--muted-foreground)] py-4">
              Todos os {total} imóveis carregados.
            </p>
          )}

          <InfiniteScroll
            onLoadMore={loadMore}
            hasMore={hasMore}
            loading={loadingMore}
          />
        </>
      )}
    </div>
  );
}

export default function ImoveisPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ImoveisContent />
    </Suspense>
  );
}
