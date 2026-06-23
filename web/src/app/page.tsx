"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Home,
  Search,
  Clock,
  ArrowRight,
} from "lucide-react";
import { ImovelCard, formatPrice } from "@/components/ImovelCard";
import type { ImovelData } from "@/components/ImovelCard";

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
function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function timeAgo(iso: string | null): string {
  if (!iso) return "Nunca executada";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `há ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `há ${hours}h`;
  const days = Math.floor(hours / 24);
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
          <Clock className="size-3" />
          {timeAgo(busca.ultima_execucao)}
        </span>
        <ArrowRight className="size-4 text-[var(--primary)]" />
      </div>
    </Link>
  );
}

// --- Main Page ---
export default function HomePage() {
  const [buscas, setBuscas] = useState<Busca[]>([]);
  const [recentes, setRecentes] = useState<ImovelData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch("/api/buscas/with-results").then((r) => r.json()),
      fetch("/api/imoveis/recentes?limit=12").then((r) => r.json()),
    ])
      .then(([buscasData, recentesData]) => {
        setBuscas(buscasData);
        setRecentes(recentesData.imoveis);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <div className="animate-pulse text-[var(--muted-foreground)]">Carregando...</div>
      </div>
    );
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
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Clock className="size-5" />
          Últimos Encontrados
        </h2>

        {recentes.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
            Nenhum imóvel encontrado ainda.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {recentes.map((i) => (
              <ImovelCard key={i.id} imovel={i} />
            ))}
          </div>
        )}
      </section>

      {/* Footer */}
      <footer className="mt-12 border-t border-[var(--border)] pt-4 text-center text-xs text-[var(--muted-foreground)]">
        Imóveis Watchdog · Dados atualizados pelo pipeline de busca
      </footer>
    </div>
  );
}
