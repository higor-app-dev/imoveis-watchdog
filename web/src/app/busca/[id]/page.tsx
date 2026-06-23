"use client";

import { Suspense, useMemo } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Search,
} from "lucide-react";
import useSWR from "swr";
import { ImovelCard, formatPrice } from "@/components/ImovelCard";
import { fetcher } from "@/lib/fetcher";
import SortBar from "@/components/SortBar";
import type { SortField, SortOrder } from "@/components/SortBar";
import InfiniteScroll from "@/components/InfiniteScroll";
import ProviderFilter from "@/components/ProviderFilter";
import { useImovelScroll } from "@/hooks/useImovelScroll";

interface Busca {
  id: number;
  nome: string;
  regiao: string;
  bairros: string | null;
  cidades: string | null;
  modalidades: string | null;
  preco_min: number | null;
  preco_max: number | null;
  area_min: number | null;
  quartos_min: number | null;
  vagas_min: number | null;
  ultima_execucao: string | null;
  ultimo_total: number | null;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex items-center justify-center py-20">
        <div className="animate-pulse text-[var(--muted-foreground)]">Carregando...</div>
      </div>
    </div>
  );
}

export default function BuscaPage() {
  return (
    <Suspense fallback={<Loading />}>
      <BuscaContent />
    </Suspense>
  );
}

function BuscaContent() {
  const params = useParams();
  const sp = useSearchParams();
  const router = useRouter();
  const id = Number(params.id);

  // Busca metadata via SWR
  const { data: busca } = useSWR<Busca>(`/api/buscas/${id}`, fetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
  });

  const sort = (sp.get("sort") as SortField) || "data";
  const order = (sp.get("order") as SortOrder) || "desc";
  const fontesRaw = sp.get("fontes") || "";
  const fontes = useMemo(
    () => fontesRaw.split(",").map((f) => f.trim()).filter(Boolean),
    [fontesRaw]
  );

  const extraParams = useMemo(
    () => ({
      sort,
      order,
      fontes: fontes.length > 0 ? fontes.join(",") : "",
    }),
    [sort, order, fontes]
  );

  const baseUrl = `/api/buscas/${id}/imoveis`;
  const { imoveis, total, loading, loadingMore, hasMore, error, loadMore } =
    useImovelScroll({ baseUrl, perPage: 24, extraParams });

  function handleSortChange(newSort: SortField, newOrder: SortOrder) {
    const q = new URLSearchParams(sp.toString());
    q.set("sort", newSort);
    q.set("order", newOrder);
    router.replace(`/busca/${id}?${q}`, { scroll: false });
  }

  function handleFontesChange(newFontes: string[]) {
    const q = new URLSearchParams(sp.toString());
    if (newFontes.length > 0) {
      q.set("fontes", newFontes.join(","));
    } else {
      q.delete("fontes");
    }
    router.replace(`/busca/${id}?${q}`, { scroll: false });
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
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link href="/" className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
          <ArrowLeft className="size-5" />
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold truncate">{busca?.nome || "Carregando..."}</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            {total} imóveis encontrados
            {!hasMore && total > 24 && " · Todos carregados"}
          </p>
        </div>
      </div>

      {/* Search Config Info */}
      {busca && (
        <div className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
          <div className="flex items-center gap-2 mb-2">
            <Search className="size-4 text-[var(--primary)]" />
            <span className="text-sm font-medium">Configuração da Busca</span>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-[var(--muted-foreground)]">
            {busca.regiao && <span>📍 {busca.regiao}</span>}
            {busca.modalidades && (
              <span>
                🏷️ {JSON.parse(busca.modalidades)
                  .map((m: string) => m === "compra" ? "Compra" : m === "aluguel" ? "Aluguel" : "Leilão")
                  .join(", ")}
              </span>
            )}
            {busca.preco_max && <span>💰 até {formatPrice(busca.preco_max)}</span>}
            {busca.area_min && <span>📐 {busca.area_min}m²+</span>}
            {busca.quartos_min && <span>🛏️ {busca.quartos_min}+ quartos</span>}
            {busca.vagas_min && <span>🚗 {busca.vagas_min}+ vagas</span>}
            {busca.ultima_execucao && <span>🕐 Última execução: {formatDate(busca.ultima_execucao)}</span>}
          </div>
        </div>
      )}

      {/* Sort + Filter Bar */}
      <div className="mb-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <SortBar sort={sort} order={order} onChange={handleSortChange} />
        </div>
        <ProviderFilter selected={fontes} onChange={handleFontesChange} buscaId={id} />
      </div>

      {/* Results */}
      {imoveis.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
          Nenhum imóvel encontrado nesta busca.
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {imoveis.map((i) => (
              <ImovelCard key={i.id} imovel={i} ref={`/busca/${id}`} />
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
