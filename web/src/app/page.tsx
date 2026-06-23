"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Home,
  Search,
  MapPin,
  DollarSign,
  Ruler,
  Car,
  Bed,
  Bath,
  Clock,
  ArrowRight,
  ExternalLink,
} from "lucide-react";

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

interface Imovel {
  id: string;
  titulo: string;
  fonte: string;
  url: string;
  bairro: string;
  cidade: string;
  modalidade: string;
  preco_venda: number | null;
  preco_aluguel: number | null;
  area_m2: number | null;
  quartos: number | null;
  banheiros: number | null;
  vagas: number | null;
  foto_url: string | null;
  data_primeira_vista: string | null;
}

// --- Helpers ---
function formatPrice(value: number | null): string {
  if (value === null || value === 0) return "";
  return `R$ ${value.toLocaleString("pt-BR")}`;
}

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

function imovelTitle(i: Imovel): string {
  const parts: string[] = [];
  if (i.titulo) return i.titulo;
  if (i.bairro) parts.push(i.bairro);
  if (i.cidade) parts.push(i.cidade);
  return parts.join(" - ") || "Imóvel";
}

// --- Components ---
function PriceTag({ imovel }: { imovel: Imovel }) {
  if (imovel.preco_venda) {
    return (
      <span className="inline-flex items-center gap-1 text-lg font-bold text-blue-600 dark:text-blue-400">
        {formatPrice(imovel.preco_venda)}
      </span>
    );
  }
  if (imovel.preco_aluguel) {
    return (
      <span className="inline-flex items-center gap-1 text-lg font-bold text-emerald-600 dark:text-emerald-400">
        {formatPrice(imovel.preco_aluguel)}/mês
      </span>
    );
  }
  return null;
}

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {children}
    </span>
  );
}

function ModalidadeBadge({ m }: { m: string }) {
  if (m === "compra" || m === "venda")
    return <Badge color="bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">Compra</Badge>;
  if (m === "aluguel")
    return <Badge color="bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">Aluguel</Badge>;
  if (m === "leilao")
    return <Badge color="bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300">Leilão</Badge>;
  return <Badge color="bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">{m}</Badge>;
}

// --- Cards ---
function ImovelCard({ imovel }: { imovel: Imovel }) {
  const title = imovelTitle(imovel);
  return (
    <div className="group rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all hover:shadow-md hover:-translate-y-0.5">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex flex-wrap gap-1">
          <ModalidadeBadge m={imovel.modalidade} />
          <Badge color="bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
            {imovel.fonte}
          </Badge>
        </div>
        <a
          href={imovel.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
        >
          <ExternalLink className="size-4" />
        </a>
      </div>

      <h3 className="font-medium text-sm leading-snug mb-2 line-clamp-2">{title}</h3>

      {imovel.bairro && (
        <p className="flex items-center gap-1 text-xs text-[var(--muted-foreground)] mb-2">
          <MapPin className="size-3 shrink-0" />
          {imovel.bairro}{imovel.cidade ? `, ${imovel.cidade}` : ""}
        </p>
      )}

      <PriceTag imovel={imovel} />

      <div className="flex flex-wrap gap-3 mt-2 text-xs text-[var(--muted-foreground)]">
        {imovel.area_m2 && (
          <span className="flex items-center gap-1">
            <Ruler className="size-3" />
            {imovel.area_m2}m²
          </span>
        )}
        {imovel.quartos && (
          <span className="flex items-center gap-1">
            <Bed className="size-3" />
            {imovel.quartos}
          </span>
        )}
        {imovel.banheiros && (
          <span className="flex items-center gap-1">
            <Bath className="size-3" />
            {imovel.banheiros}
          </span>
        )}
        {imovel.vagas && (
          <span className="flex items-center gap-1">
            <Car className="size-3" />
            {imovel.vagas}
          </span>
        )}
      </div>
    </div>
  );
}

function BuscaCard({ busca }: { busca: Busca }) {
  const desc = buscaDesc(busca);
  return (
    <Link
      href={`/busca/${busca.id}`}
      className="block rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 transition-all hover:shadow-md hover:-translate-y-0.5"
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-semibold text-base">{busca.nome}</h3>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-2xl font-bold text-[var(--primary)]">{busca.resultado_count}</span>
          <span className="text-xs text-[var(--muted-foreground)]">imóveis</span>
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
  const [recentes, setRecentes] = useState<Imovel[]>([]);
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
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
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
