"use client";

import { useEffect, useState, useCallback } from "react";
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
  Search,
  X,
  ChevronLeft,
  ChevronRight,
  Filter,
  SlidersHorizontal,
} from "lucide-react";

// --- Types ---
interface Imovel {
  id: string;
  titulo: string;
  fonte: string;
  url: string;
  bairro: string;
  cidade: string;
  uf: string;
  tipo: string | null;
  modalidade: string;
  preco_venda: number | null;
  preco_aluguel: number | null;
  area_m2: number | null;
  quartos: number | null;
  banheiros: number | null;
  vagas: number | null;
  data_primeira_vista: string | null;
}

// --- Helpers ---
function formatPrice(val: number | null): string {
  if (val === null || val === 0) return "";
  return `R$ ${val.toLocaleString("pt-BR")}`;
}

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {children}
    </span>
  );
}

function ModalidadeBadge({ m }: { m: string }) {
  if (m === "compra" || m === "venda") return <Badge color="bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">Compra</Badge>;
  if (m === "aluguel") return <Badge color="bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">Aluguel</Badge>;
  if (m === "leilao") return <Badge color="bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300">Leilão</Badge>;
  return <Badge color="bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">{m}</Badge>;
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

function ImovelCard({ imovel }: { imovel: Imovel }) {
  const title = imovel.titulo || `${imovel.bairro}${imovel.cidade ? `, ${imovel.cidade}` : ""}`;
  return (
    <div className="group rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all hover:shadow-md hover:-translate-y-0.5">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex flex-wrap gap-1">
          <ModalidadeBadge m={imovel.modalidade} />
          <Badge color="bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">{imovel.fonte}</Badge>
        </div>
        <a href={imovel.url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
          <ExternalLink className="size-4" />
        </a>
      </div>
      <h3 className="font-medium text-sm leading-snug mb-2 line-clamp-2">{title}</h3>
      {imovel.bairro && (
        <p className="flex items-center gap-1 text-xs text-[var(--muted-foreground)] mb-2">
          <MapPin className="size-3 shrink-0" />
          {imovel.bairro}{imovel.cidade ? `, ${imovel.cidade}` : ""} - {imovel.uf}
        </p>
      )}
      <PriceTag imovel={imovel} />
      <div className="flex flex-wrap gap-3 mt-2 text-xs text-[var(--muted-foreground)]">
        {imovel.area_m2 && <span className="flex items-center gap-1"><Ruler className="size-3" />{imovel.area_m2}m²</span>}
        {imovel.quartos && <span className="flex items-center gap-1"><Bed className="size-3" />{imovel.quartos}</span>}
        {imovel.banheiros && <span className="flex items-center gap-1"><Bath className="size-3" />{imovel.banheiros}</span>}
        {imovel.vagas && <span className="flex items-center gap-1"><Car className="size-3" />{imovel.vagas}</span>}
      </div>
    </div>
  );
}

// --- Page ---
export default function ImoveisPage() {
  const [imoveis, setImoveis] = useState<Imovel[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [bairros, setBairros] = useState<string[]>([]);
  const [tipos, setTipos] = useState<string[]>([]);
  const [fontes, setFontes] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  // Filters
  const [fBairro, setFBairro] = useState("");
  const [fModalidade, setFModalidade] = useState("");
  const [fFonte, setFFonte] = useState("");
  const [fPrecoMin, setFPrecoMin] = useState("");
  const [fPrecoMax, setFPrecoMax] = useState("");
  const [fAreaMin, setFAreaMin] = useState("");
  const [fQuartosMin, setFQuartosMin] = useState("");
  const [fVagasMin, setFVagasMin] = useState("");
  const [page, setPage] = useState(0);
  const PER_PAGE = 50;

  // Load filter options once
  useEffect(() => {
    Promise.all([
      fetch("/api/imoveis/bairros").then((r) => r.json()),
      fetch("/api/imoveis/tipos").then((r) => r.json()),
      fetch("/api/imoveis/fontes").then((r) => r.json()),
    ]).then(([b, t, f]) => {
      setBairros(b);
      setTipos(t);
      setFontes(f);
    }).catch(console.error);
  }, []);

  const fetchImoveis = useCallback(async () => {
    setLoading(true);
    try {
      const sp = new URLSearchParams();
      sp.set("limit", String(PER_PAGE));
      sp.set("offset", String(page * PER_PAGE));
      if (fBairro) sp.set("bairro", fBairro);
      if (fModalidade) sp.set("modalidade", fModalidade);
      if (fFonte) sp.set("fonte", fFonte);
      if (fPrecoMin) sp.set("preco_min", fPrecoMin);
      if (fPrecoMax) sp.set("preco_max", fPrecoMax);
      if (fAreaMin) sp.set("area_min", fAreaMin);
      if (fQuartosMin) sp.set("quartos_min", fQuartosMin);
      if (fVagasMin) sp.set("vagas_min", fVagasMin);

      const res = await fetch(`/api/imoveis?${sp}`);
      const data = await res.json();
      setImoveis(data.imoveis);
      setTotal(data.total);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [fBairro, fModalidade, fFonte, fPrecoMin, fPrecoMax, fAreaMin, fQuartosMin, fVagasMin, page]);

  useEffect(() => {
    fetchImoveis();
  }, [fetchImoveis]);

  const totalPages = Math.ceil(total / PER_PAGE);
  const hasFilters = fBairro || fModalidade || fFonte || fPrecoMin || fPrecoMax || fAreaMin || fQuartosMin || fVagasMin;

  const clearFilters = () => {
    setFBairro("");
    setFModalidade("");
    setFFonte("");
    setFPrecoMin("");
    setFPrecoMax("");
    setFAreaMin("");
    setFQuartosMin("");
    setFVagasMin("");
    setPage(0);
  };

  const activeCount = [fBairro, fModalidade, fFonte, fPrecoMin, fPrecoMax, fAreaMin, fQuartosMin, fVagasMin].filter(Boolean).length;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
            <ArrowLeft className="size-5" />
          </Link>
          <div>
            <h1 className="text-xl font-bold">Explorar Imóveis</h1>
            <p className="text-sm text-[var(--muted-foreground)]">{total} imóveis encontrados</p>
          </div>
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition-colors ${
            showFilters || hasFilters
              ? "border-[var(--primary)] text-[var(--primary)]"
              : "border-[var(--border)] text-[var(--muted-foreground)]"
          }`}
        >
          <SlidersHorizontal className="size-4" />
          Filtros
          {activeCount > 0 && (
            <span className="inline-flex items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] size-5 text-xs font-bold">
              {activeCount}
            </span>
          )}
        </button>
      </div>

      {/* Filter Panel */}
      {showFilters && (
        <div className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Filter className="size-4 text-[var(--muted-foreground)]" />
              <span className="text-sm font-medium">Filtros Avançados</span>
            </div>
            {hasFilters && (
              <button onClick={clearFilters} className="flex items-center gap-1 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
                <X className="size-3" /> Limpar todos
              </button>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="block text-xs text-[var(--muted-foreground)] mb-1">Bairro</label>
              <input
                type="text" list="bairros-list" placeholder="Qualquer bairro..."
                value={fBairro} onChange={(e) => { setFBairro(e.target.value); setPage(0); }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]"
              />
              <datalist id="bairros-list">
                {bairros.map((b) => <option key={b} value={b} />)}
              </datalist>
            </div>

            <div>
              <label className="block text-xs text-[var(--muted-foreground)] mb-1">Modalidade</label>
              <select value={fModalidade} onChange={(e) => { setFModalidade(e.target.value); setPage(0); }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]">
                <option value="">Todas</option>
                <option value="compra">Compra</option>
                <option value="venda">Venda</option>
                <option value="aluguel">Aluguel</option>
                <option value="leilao">Leilão</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-[var(--muted-foreground)] mb-1">Fonte</label>
              <select value={fFonte} onChange={(e) => { setFFonte(e.target.value); setPage(0); }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]">
                <option value="">Todas</option>
                {fontes.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs text-[var(--muted-foreground)] mb-1">Preço min.</label>
                <input type="number" placeholder="R$ 0" value={fPrecoMin} onChange={(e) => { setFPrecoMin(e.target.value); setPage(0); }}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]" />
              </div>
              <div>
                <label className="block text-xs text-[var(--muted-foreground)] mb-1">Preço máx.</label>
                <input type="number" placeholder="R$ ..." value={fPrecoMax} onChange={(e) => { setFPrecoMax(e.target.value); setPage(0); }}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]" />
              </div>
            </div>

            <div>
              <label className="block text-xs text-[var(--muted-foreground)] mb-1">Área mín. (m²)</label>
              <input type="number" placeholder="0" value={fAreaMin} onChange={(e) => { setFAreaMin(e.target.value); setPage(0); }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]" />
            </div>

            <div>
              <label className="block text-xs text-[var(--muted-foreground)] mb-1">Quartos mín.</label>
              <select value={fQuartosMin} onChange={(e) => { setFQuartosMin(e.target.value); setPage(0); }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]">
                <option value="">Qualquer</option>
                <option value="1">1+</option>
                <option value="2">2+</option>
                <option value="3">3+</option>
                <option value="4">4+</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-[var(--muted-foreground)] mb-1">Vagas mín.</label>
              <select value={fVagasMin} onChange={(e) => { setFVagasMin(e.target.value); setPage(0); }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]">
                <option value="">Qualquer</option>
                <option value="1">1+</option>
                <option value="2">2+</option>
                <option value="3">3+</option>
              </select>
            </div>
          </div>
        </div>
      )}

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

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-6">
              <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
                className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40 hover:bg-[var(--muted)] transition-colors">
                <ChevronLeft className="size-4" /> Anterior
              </button>
              <span className="text-sm text-[var(--muted-foreground)]">
                Página {page + 1} de {totalPages}
              </span>
              <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
                className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40 hover:bg-[var(--muted)] transition-colors">
                Próxima <ChevronRight className="size-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
