"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Search,
} from "lucide-react";
import { ImovelCard } from "@/components/ImovelCard";
import type { ImovelData } from "@/components/ImovelCard";

const PER_PAGE = 50;

export default function ImoveisPage() {
  const [imoveis, setImoveis] = useState<ImovelData[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [page, setPage] = useState(0);

  const fetchImoveis = useCallback(async () => {
    setLoading(true);
    try {
      const sp = new URLSearchParams();
      sp.set("limit", String(PER_PAGE));
      sp.set("offset", String(page * PER_PAGE));
      if (searchTerm) sp.set("bairro", searchTerm);

      const res = await fetch(`/api/imoveis?${sp}`);
      const data = await res.json();
      setImoveis(data.imoveis);
      setTotal(data.total);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [searchTerm, page]);

  useEffect(() => {
    fetchImoveis();
  }, [fetchImoveis]);

  const totalPages = Math.ceil(total / PER_PAGE);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
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

      {/* Simple search bar */}
      <div className="mb-6">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[var(--muted-foreground)]" />
          <input
            type="text"
            placeholder="Buscar por bairro..."
            value={searchTerm}
            onChange={(e) => { setSearchTerm(e.target.value); setPage(0); }}
            className="w-full rounded-xl border border-[var(--border)] bg-[var(--background)] pl-9 pr-4 py-2.5 text-sm outline-none focus:border-[var(--primary)] transition-colors"
          />
        </div>
      </div>

      {/* Results */}
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
