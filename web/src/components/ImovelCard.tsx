import Link from "next/link";
import {
  MapPin,
  Ruler,
  Bed,
  Bath,
  Car,
  DollarSign,
  Building,
  FileText,
  ExternalLink,
  ImageIcon,
} from "lucide-react";

// --- Types ---
export interface ImovelData {
  id: string;
  titulo: string;
  fonte: string;
  url: string;
  endereco: string | null;
  bairro: string;
  cidade: string;
  uf: string;
  tipo: string | null;
  modalidade: string;
  preco_venda: number | null;
  preco_aluguel: number | null;
  condominio: number | null;
  iptu: number | null;
  area_m2: number | null;
  quartos: number | null;
  banheiros: number | null;
  vagas: number | null;
  descricao: string | null;
  data_primeira_vista: string | null;
  foto_url: string | null;
  latitude: number | null;
  longitude: number | null;
}

// --- Helpers ---
export function formatPrice(val: number | null): string {
  if (val === null || val === 0) return "";
  return `R$ ${val.toLocaleString("pt-BR")}`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

// --- Imóvel Card ---
export function ImovelCard({ imovel }: { imovel: ImovelData }) {
  const title = imovel.titulo || `${imovel.bairro}${imovel.cidade ? `, ${imovel.cidade}` : ""}`;

  return (
    <Link
      href={`/imovel/${encodeURIComponent(imovel.id)}`}
      className="group block rounded-xl border border-[var(--border)] bg-[var(--card)] overflow-hidden transition-all hover:shadow-md hover:-translate-y-0.5"
    >
      {/* Image */}
      <div className="relative aspect-[16/9] bg-[var(--muted)] overflow-hidden">
        {imovel.foto_url ? (
          <img
            src={imovel.foto_url}
            alt={title}
            className="size-full object-cover group-hover:scale-105 transition-transform duration-300"
            loading="lazy"
          />
        ) : (
          <div className="flex items-center justify-center size-full text-[var(--muted-foreground)]">
            <ImageIcon className="size-10 opacity-40" />
          </div>
        )}
        <div className="absolute top-2 left-2 flex gap-1">
          <ModalidadeBadge m={imovel.modalidade} />
          <Badge color="bg-purple-100/90 text-purple-700 dark:bg-purple-900/90 dark:text-purple-300">
            {imovel.fonte}
          </Badge>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        <h3 className="font-medium text-sm leading-snug mb-2 line-clamp-2">{title}</h3>

        {imovel.bairro && (
          <p className="flex items-center gap-1 text-xs text-[var(--muted-foreground)] mb-2">
            <MapPin className="size-3 shrink-0" />
            {imovel.cidade ? `${imovel.bairro}, ${imovel.cidade} - ${imovel.uf}` : imovel.bairro}
          </p>
        )}

        {/* Prices */}
        <div className="space-y-1 mb-2">
          {imovel.preco_venda ? (
            <span className="flex items-center gap-1 text-base font-bold text-blue-600 dark:text-blue-400">
              <DollarSign className="size-4" />
              {formatPrice(imovel.preco_venda)}
            </span>
          ) : imovel.preco_aluguel ? (
            <span className="flex items-center gap-1 text-base font-bold text-emerald-600 dark:text-emerald-400">
              <DollarSign className="size-4" />
              {formatPrice(imovel.preco_aluguel)}/mês
            </span>
          ) : null}

          {(imovel.condominio ?? 0) > 0 && (
            <span className="flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
              <Building className="size-3" />
              Cond. {formatPrice(imovel.condominio)}
            </span>
          )}
          {(imovel.iptu ?? 0) > 0 && (
            <span className="flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
              <FileText className="size-3" />
              IPTU {formatPrice(imovel.iptu)}/ano
            </span>
          )}
        </div>

        {/* Specs */}
        <div className="flex flex-wrap gap-3 text-xs text-[var(--muted-foreground)]">
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
    </Link>
  );
}
