"use client";

import { Suspense, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Home,
  Search,
  Clock,
  ArrowRight,
  Timer,
} from "lucide-react";
import useSWR from "swr";
import { ImovelCard, formatPrice } from "@/components/ImovelCard";
import type { ImovelData } from "@/components/ImovelCard";
import { fetcher } from "@/lib/fetcher";
import InfiniteScroll from "@/components/InfiniteScroll";
import ProviderFilter from "@/components/ProviderFilter";
import { useImovelScroll } from "@/hooks/useImovelScroll";

// --- Types ---
interface Busca {
  id: number;
  nome: string;
  regiao: string;
  bairros: string | null;
  modalidades: string | null;
  preco_min: number | null;
  preco_max: number | null;
  area_min: number | null;
  quartos_min: number | null;
  vagas_min: number | null;
  ultima_execucao: string | null;
  ultimo_total: number | null;
  resultado_count: number;
}

// --- Helpers ---
function timeAgo(iso: string | null): string {
  if (!iso) return "Nunca executada";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `há ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `há ${hours}h`;
  const days = Math.floor(hours / 60 / 24);
  return `há ${days}d`;
}

function buscaDesc(b: Busca): string {
  const parts: string[] = [];
  if (b.regiao) parts.push(b.regiao);
  if (b.modalidades) {
    parts.push(
      JSON.parse(b.modalidades)
        .map((m: string) => (m === "compra" ? "Compra" : m === "aluguel" ? "Aluguel" : "Leilão"))
        .join(", ")
    );
  }
  if (b.preco_max) parts.push(`até ${formatPrice(b.preco_max)}`);
  if (b.area_min) parts.push(`${b.area_min}m²+`);
  if (b.quartos_min) parts.push(`${b.quartos_min}+ quartos`);
  if (b.vagas_min) parts.push(`${b.vagas_min}+ vagas`);
  return parts.join(" · ");
}

function BuscaCard({ busca }: { busca: Busca }) {
  const desc = buscaDesc(busca);
  return (
    <Link
      href={`/busca/${busca.id}`}
      className="block rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 transition-all hover:shadow-md hover:-translate-y-0.5 overflow-hidden min-w-0"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <h3 className="font-semibold text-base truncate min-w-0">{busca.nome}</h3>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-2xl font-bold text-[var(--primary)]">{busca.resultado_count}</span>
          <span className="text-xs text-[var(--muted-foreground)] whitespace-nowrap">imóveis</span>
        </div>
      </div>

      <p className="text-xs text-[var(--muted-foreground)] mb-3 line-clamp-2">{desc}</p>

      <div className="flex items-center justify-between text-xs text-[var(--muted-foreground)]">
        <span className="flex items-center gap-1">
          <Timer className="size-3" />
          {timeAgo(busca.ultima_execucao)}
        </span>
        <ArrowRight className="size-4 text-[var(--primary)]" />
      </div>
    </Link>
  );
}

// --- Main Home Page ---
function HomeContent() {
  const sp = useSearchParams();
  const router = useRouter();

  // Buscas via SWR
  const { data: buscas = [] } = useSWR<Busca[]>("/api/buscas/with-results", fetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
  });

  // Fontes filter from URL
  const fontesRaw = sp.get("fontes") || "";
  const fontes = useMemo(
    () => fontesRaw.split(",").map((f) => f.trim()).filter(Boolean),
    [fontesRaw]
  );

  const extraParams = useMemo(
    () => ({
      sort: "data",
      order: "desc",
      fontes: fontes.length > 0 ? fontes.join(",") : "",
    }),
    [fontes]
  );

  // Infinite scroll for recent imoveis (now SWR-based internally)
  const { imoveis, total, loading, loadingMore, hasMore, error, loadMore } =
    useImovelScroll({
      baseUrl: "/api/imoveis",
      perPage: 24,
      extraParams,
    });

  function handleFontesChange(newFontes: string[]) {
    const q = new URLSearchParams(sp.toString());
    if (newFontes.length > 0) {
      q.set("fontes", newFontes.join(","));
    } else {
      q.delete("fontes");
    }
    router.replace(`/?${q}`, { scroll: false });
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8 overflow-x-hidden">
      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <Home className="size-7 text-[var(--primary)]" />
          <h1 className="text-2xl font-bold">Imóveis Watchdog</h1>
        </div>
        <p className="text-sm text-[var(--muted-foreground)] ml-10">
          Pipeline de busca unificada · {buscas.reduce((a, b) => a + b.resultado_count, 0)} imóveis no total
        </p>
      </header>

      {/* Buscas Section */}
      <section className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Search className="size-5" />
            Últimas Buscas
          </h2>
          <Link
            href="/imoveis"
            className="text-sm text-[var(--primary)] hover:underline flex items-center gap-1"
          >
            Explorar todos <ArrowRight className="size-3" />
          </Link>
        </div>

        {buscas.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
            Nenhuma busca cadastrada ainda.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {buscas.map((b) => (
              <BuscaCard key={b.id} busca={b} />
            ))}
          </div>
        )}
      </section>

      {/* Recentes Section */}
      <section>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Clock className="size-5" />
            Últimos Encontrados
          </h2>
        </div>

        <div className="mb-4">
          <ProviderFilter selected={fontes} onChange={handleFontesChange} />
        </div>

        {error && (
          <div className="rounded-xl border border-red-300 bg-red-50 dark:bg-red-950 dark:border-red-800 p-4 text-center text-sm text-red-700 dark:text-red-300 mb-4">
            Erro: {error}
          </div>
        )}

        {loading && imoveis.length === 0 ? (
          <div className="flex items-center justify-center py-16">
            <div className="animate-pulse text-[var(--muted-foreground)]">Carregando...</div>
          </div>
        ) : imoveis.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
            Nenhum imóvel encontrado.
          </div>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
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
      </section>

      <footer className="mt-12 border-t border-[var(--border)] pt-4 text-center text-xs text-[var(--muted-foreground)]">
        Imóveis Watchdog · Dados atualizados pelo pipeline de busca
      </footer>
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-dvh items-center justify-center">
        <div className="animate-pulse text-[var(--muted-foreground)]">Carregando...</div>
      </div>
    }>
      <HomeContent />
    </Suspense>
  );
}
