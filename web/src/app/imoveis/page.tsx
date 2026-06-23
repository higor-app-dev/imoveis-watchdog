"use client";

import { Suspense } from "react";
import { useEffect, useState, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Search,
} from "lucide-react";
import { ImovelCard } from "@/components/ImovelCard";
import type { ImovelData } from "@/components/ImovelCard";
import SortBar from "@/components/SortBar";
import type { SortField, SortOrder } from "@/components/SortBar";

const PER_PAGE = 50;

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

  const [imoveis, setImoveis] = useState<ImovelData[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState(sp.get("bairro") || "");
  const [page, setPage] = useState(0);

  const sort = (sp.get("sort") as SortField) || "data";
  const order = (sp.get("order") as SortOrder) || "desc";

  function buildUrl(s: SortField, o: SortOrder, p: number, bairro: string) {
    const q = new URLSearchParams();
    q.set("limit", String(PER_PAGE));
    q.set("offset", String(p * PER_PAGE));
    q.set("sort", s);
    q.set("order", o);
    if (bairro) q.set("bairro", bairro);
    return `/api/imoveis?${q}`;
  }

  const fetchImoveis = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(buildUrl(sort, order, page, searchTerm));
      const data = await res.json();
      setImoveis(data.imoveis);
      setTotal(data.total);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [sort, order, page, searchTerm]);

  useEffect(() => {
    fetchImoveis();
  }, [fetchImoveis]);

  function handleSortChange(newSort: SortField, newOrder: SortOrder) {
    setPage(0);
    const q = new URLSearchParams(sp.toString());
    q.set("sort", newSort);
    q.set("order", newOrder);
    router.replace(`/imoveis?${q}`, { scroll: false });
  }

  function handleSearch(value: string) {
    setSearchTerm(value);
    setPage(0);
  }

  const totalPages = Math.ceil(total / PER_PAGE);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3 min-w-0">
          <Link href="/" className="shrink-0 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
            <ArrowLeft className="size-5" />
          </Link>
          <div className="min-w-0">
            <h1 className="text-xl font-bold">Explorar Imóveis</h1>
            <p className="text-sm text-[var(--muted-foreground)]">{total} imóveis encontrados</p>
          </div>
        </div>
      </div>

      <div className="mb-6 flex flex-col sm:flex-row gap-3">
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

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-pulse text-[var(--muted-foreground)]">Buscando imóveis...</div>
        </div>
      ) : imoveis.length === 0 ? (
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

export default function ImoveisPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ImoveisContent />
    </Suspense>
  );
}
