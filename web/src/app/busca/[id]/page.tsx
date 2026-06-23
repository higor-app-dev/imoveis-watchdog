"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  MapPin,
  Ruler,
  Bed,
  Bath,
  Car,
  DollarSign,
  ExternalLink,
  Filter,
  X,
  Search,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

// --- Types ---
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
function formatPrice(val: number | null): string {
  if (val === null || val === 0) return "";
  return `R$ ${val.toLocaleString("pt-BR")}`;
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

// --- Badges ---
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

function ImovelCard({ imovel }: { imovel: Imovel }) {
  const title = imovel.titulo || `${imovel.bairro}${imovel.cidade ? `, ${imovel.cidade}` : ""}`;
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
          <span className="flex items-center gap-1"><Ruler className="size-3" />{imovel.area_m2}m²</span>
        )}
        {imovel.quartos && (
          <span className="flex items-center gap-1"><Bed className="size-3" />{imovel.quartos}</span>
        )}
        {imovel.banheiros && (
          <span className="flex items-center gap-1"><Bath className="size-3" />{imovel.banheiros}</span>
        )}
        {imovel.vagas && (
          <span className="flex items-center gap-1"><Car className="size-3" />{imovel.vagas}</span>
        )}
      </div>
    </div>
  );
}

function PriceTag({ imovel }: { imovel: Imovel }) {
  if (imovel.preco_venda) {
    return <span className="inline-flex items-center gap-1 text-lg font-bold text-blue-600 dark:text-blue-400">{formatPrice(imovel.preco_venda)}</span>;
  }
  if (imovel.preco_aluguel) {
    return <span className="inline-flex items-center gap-1 text-lg font-bold text-emerald-600 dark:text-emerald-400">{formatPrice(imovel.preco_aluguel)}/mês</span>;
  }
  return null;
}

// --- Page ---
export default function BuscaPage() {
  const params = useParams();
  const id = Number(params.id);
  const [busca, setBusca] = useState<Busca | null>(null);
  const [imoveis, setImoveis] = useState<Imovel[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filtroBairro, setFiltroBairro] = useState("");
  const [filtroTipo, setFiltroTipo] = useState("");
  const [filtroModalidade, setFiltroModalidade] = useState("");
  const [filtroPrecoMax, setFiltroPrecoMax] = useState("");
  const [page, setPage] = useState(0);
  const PER_PAGE = 50;

  const fetchImoveis = useCallback(async () => {
    setLoading(true);
    try {
      const sp = new URLSearchParams();
      sp.set("limit", String(PER_PAGE));
      sp.set("offset", String(page * PER_PAGE));
      if (filtroBairro) sp.set("bairro", filtroBairro);
      if (filtroTipo) sp.set("tipo", filtroTipo);
      if (filtroModalidade) sp.set("modalidade", filtroModalidade);
      if (filtroPrecoMax) sp.set("preco_max", filtroPrecoMax);

      const res = await fetch(`/api/buscas/${id}/imoveis?${sp}`);
      const data = await res.json();
      setBusca(data.busca);
      setImoveis(data.imoveis);
      setTotal(data.total);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [id, filtroBairro, filtroTipo, filtroModalidade, filtroPrecoMax, page]);

  useEffect(() => {
    fetchImoveis();
  }, [fetchImoveis]);

  const totalPages = Math.ceil(total / PER_PAGE);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link href="/" className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
          <ArrowLeft className="size-5" />
        </Link>
        <div>
          <h1 className="text-xl font-bold">{busca?.nome || "Carregando..."}</h1>
          <p className="text-sm text-[var(--muted-foreground)]">{total} imóveis encontrados</p>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="size-4 text-[var(--muted-foreground)]" />
          <span className="text-sm font-medium">Filtros</span>
        </div>
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Bairro..."
            value={filtroBairro}
            onChange={(e) => { setFiltroBairro(e.target.value); setPage(0); }}
            className="min-w-[160px] rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)] transition-colors"
          />
          <select
            value={filtroModalidade}
            onChange={(e) => { setFiltroModalidade(e.target.value); setPage(0); }}
            className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)] transition-colors"
          >
            <option value="">Todas modalidades</option>
            <option value="compra">Compra</option>
            <option value="venda">Venda</option>
            <option value="aluguel">Aluguel</option>
            <option value="leilao">Leilão</option>
          </select>
          <div className="relative">
            <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[var(--muted-foreground)]" />
            <input
              type="number"
              placeholder="Preço máximo"
              value={filtroPrecoMax}
              onChange={(e) => { setFiltroPrecoMax(e.target.value); setPage(0); }}
              className="w-[160px] rounded-lg border border-[var(--border)] bg-[var(--background)] pl-8 pr-3 py-2 text-sm outline-none focus:border-[var(--primary)] transition-colors"
            />
          </div>

          {(filtroBairro || filtroModalidade || filtroPrecoMax) && (
            <button
              onClick={() => {
                setFiltroBairro("");
                setFiltroTipo("");
                setFiltroModalidade("");
                setFiltroPrecoMax("");
                setPage(0);
              }}
              className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            >
              <X className="size-3" />
              Limpar
            </button>
          )}
        </div>
      </div>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-pulse text-[var(--muted-foreground)]">Buscando imóveis...</div>
        </div>
      ) : imoveis.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
          Nenhum imóvel encontrado com esses filtros.
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {imoveis.map((i) => (
              <ImovelCard key={i.id} imovel={i} />
            ))}
          </div>

          {/* Pagination */}
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
