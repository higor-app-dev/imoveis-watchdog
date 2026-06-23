"use client";

import { Suspense } from "react";
import { useEffect, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Search,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { ImovelCard, formatPrice } from "@/components/ImovelCard";
import type { ImovelData } from "@/components/ImovelCard";
import SortBar from "@/components/SortBar";
import type { SortField, SortOrder } from "@/components/SortBar";

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

  const [busca, setBusca] = useState<Busca | null>(null);
  const [imoveis, setImoveis] = useState<ImovelData[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const PER_PAGE = 50;

  const sort = (sp.get("sort") as SortField) || "data";
  const order = (sp.get("order") as SortOrder) || "desc";

  function buildUrl(s: SortField, o: SortOrder, p: number) {
    const q = new URLSearchParams();
    q.set("limit", String(PER_PAGE));
    q.set("offset", String(p * PER_PAGE));
    q.set("sort", s);
    q.set("order", o);
    return `/api/buscas/${id}/imoveis?${q}`;
  }

  useEffect(() => {
    setLoading(true);
    fetch(buildUrl(sort, order, page))
      .then((r) => r.json())
      .then((data) => {
        setBusca(data.busca);
        setImoveis(data.imoveis);
        setTotal(data.total);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id, sort, order, page]);

  function handleSortChange(newSort: SortField, newOrder: SortOrder) {
    setPage(0);
    const q = new URLSearchParams(sp.toString());
    q.set("sort", newSort);
    q.set("order", newOrder);
    router.replace(`/busca/${id}?${q}`, { scroll: false });
  }

  const totalPages = Math.ceil(total / PER_PAGE);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link href="/" className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
          <ArrowLeft className="size-5" />
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold truncate">{busca?.nome || "Carregando..."}</h1>
          <p className="text-sm text-[var(--muted-foreground)]">{total} imóveis encontrados</p>
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

      {/* Sort Bar */}
      <div className="mb-4">
        <SortBar sort={sort} order={order} onChange={handleSortChange} />
      </div>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-pulse text-[var(--muted-foreground)]">Buscando imóveis...</div>
        </div>
      ) : imoveis.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
          Nenhum imóvel encontrado nesta busca.
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {imoveis.map((i) => (
              <ImovelCard key={i.id} imovel={i} />
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-6">
              <button
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40 hover:bg-[var(--muted)] transition-colors"
              >
                <ChevronLeft className="size-4" /> Anterior
              </button>
              <span className="text-sm text-[var(--muted-foreground)]">
                Página {page + 1} de {totalPages}
              </span>
              <button
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page >= totalPages - 1}
                className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40 hover:bg-[var(--muted)] transition-colors"
              >
                Próxima <ChevronRight className="size-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
