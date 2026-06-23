"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  MapPin,
  Ruler,
  Bed,
  Bath,
  Car,
  DollarSign,
  Building,
  FileText,
  ExternalLink,
  Clock,
  Tag,
  Home,
  Hash,
  Globe,
  ImageIcon,
} from "lucide-react";
import type { ImovelData } from "@/components/ImovelCard";
import { formatPrice, formatDate } from "@/components/ImovelCard";

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>
      {children}
    </span>
  );
}

function DetailRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-[var(--border)] last:border-0">
      <span className="shrink-0 text-[var(--muted-foreground)]">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-[var(--muted-foreground)]">{label}</p>
        <p className="text-sm font-medium truncate">{value ?? "—"}</p>
      </div>
    </div>
  );
}

export default function ImovelDetailPage() {
  const params = useParams();
  const id = decodeURIComponent(params.id as string);
  const [imovel, setImovel] = useState<ImovelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [imgError, setImgError] = useState(false);
  const [showMap, setShowMap] = useState(false);

  useEffect(() => {
    fetch(`/api/imoveis/${encodeURIComponent(id)}`)
      .then((r) => {
        if (!r.ok) throw new Error("Not found");
        return r.json();
      })
      .then(setImovel)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <div className="animate-pulse text-[var(--muted-foreground)]">Carregando...</div>
      </div>
    );
  }

  if (!imovel) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-center">
        <h1 className="text-xl font-bold mb-2">Imóvel não encontrado</h1>
        <Link href="/" className="text-sm text-[var(--primary)] hover:underline">
          ← Voltar ao início
        </Link>
      </div>
    );
  }

  const title = imovel.titulo || `${imovel.bairro}${imovel.cidade ? `, ${imovel.cidade}` : ""}`;
  const images = imovel.foto_url ? [imovel.foto_url] : [];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Back */}
      <div className="mb-6">
        <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
          <ArrowLeft className="size-4" />
          Voltar
        </Link>
      </div>

      <div className="grid gap-8 lg:grid-cols-5">
        {/* Image Gallery */}
        <div className="lg:col-span-3">
          <div className="rounded-xl overflow-hidden bg-[var(--muted)] border border-[var(--border)]">
            {images.length > 0 ? (
              <div className="space-y-2">
                {images.map((url, i) => (
                  <div key={i} className="relative aspect-[16/10]">
                    <img
                      src={url}
                      alt={`${title} - foto ${i + 1}`}
                      className="size-full object-cover"
                      onError={() => setImgError(true)}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center aspect-[16/10] text-[var(--muted-foreground)]">
                <ImageIcon className="size-16 mb-2 opacity-30" />
                <span className="text-sm">Sem foto disponível</span>
              </div>
            )}
          </div>

          {/* Map */}
          {imovel.latitude && imovel.longitude && (
            <div className="mt-4">
              <button
                onClick={() => setShowMap(!showMap)}
                className="flex items-center gap-1.5 text-sm text-[var(--primary)] hover:underline mb-2"
              >
                <Globe className="size-4" />
                {showMap ? "Ocultar mapa" : "Ver no mapa"}
              </button>
              {showMap && (
                <div className="rounded-xl overflow-hidden border border-[var(--border)] h-[300px]">
                  <iframe
                    title="Localização"
                    width="100%"
                    height="100%"
                    frameBorder="0"
                    src={`https://www.openstreetmap.org/export/embed.html?bbox=${imovel.longitude - 0.01}%2C${imovel.latitude - 0.01}%2C${imovel.longitude + 0.01}%2C${imovel.latitude + 0.01}&layer=mapnik&marker=${imovel.latitude}%2C${imovel.longitude}`}
                  />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Info Panel */}
        <div className="lg:col-span-2 space-y-6">
          {/* Badges + Header */}
          <div>
            <div className="flex flex-wrap gap-1.5 mb-3">
              <Badge color="bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                {imovel.fonte}
              </Badge>
              <Badge color={`${
                imovel.modalidade === "compra" || imovel.modalidade === "venda"
                  ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                  : imovel.modalidade === "aluguel"
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300"
                  : "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
              }`}>
                {imovel.modalidade === "compra" ? "Compra" : imovel.modalidade === "venda" ? "Venda" : imovel.modalidade === "aluguel" ? "Aluguel" : imovel.modalidade === "leilao" ? "Leilão" : imovel.modalidade}
              </Badge>
              {imovel.tipo && (
                <Badge color="bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                  {imovel.tipo}
                </Badge>
              )}
            </div>

            <h1 className="text-lg font-bold leading-snug mb-1">{title}</h1>
          </div>

          {/* Main Price */}
          <div className="rounded-xl bg-[var(--muted)] p-4">
            {imovel.preco_venda ? (
              <div className="text-center">
                <p className="text-xs text-[var(--muted-foreground)] mb-1">Preço de venda</p>
                <p className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                  {formatPrice(imovel.preco_venda)}
                </p>
              </div>
            ) : imovel.preco_aluguel ? (
              <div className="text-center">
                <p className="text-xs text-[var(--muted-foreground)] mb-1">Aluguel</p>
                <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                  {formatPrice(imovel.preco_aluguel)}/mês
                </p>
              </div>
            ) : (
              <p className="text-center text-sm text-[var(--muted-foreground)]">Preço não informado</p>
            )}
          </div>

          {/* Details */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
              Detalhes
            </h2>
            <div className="divide-y divide-[var(--border)]">
              <DetailRow icon={<Ruler className="size-4" />} label="Área" value={imovel.area_m2 ? `${imovel.area_m2} m²` : "—"} />
              <DetailRow icon={<Bed className="size-4" />} label="Quartos" value={imovel.quartos} />
              <DetailRow icon={<Bath className="size-4" />} label="Banheiros" value={imovel.banheiros} />
              <DetailRow icon={<Car className="size-4" />} label="Vagas" value={imovel.vagas} />
              {(imovel.condominio ?? 0) > 0 && (
                <DetailRow icon={<Building className="size-4" />} label="Condomínio" value={formatPrice(imovel.condominio)} />
              )}
              {(imovel.iptu ?? 0) > 0 && (
                <DetailRow icon={<FileText className="size-4" />} label="IPTU" value={`${formatPrice(imovel.iptu)}/ano`} />
              )}
            </div>
          </div>

          {/* Location */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
              Localização
            </h2>
            <div className="divide-y divide-[var(--border)]">
              <DetailRow icon={<MapPin className="size-4" />} label="Bairro" value={imovel.bairro} />
              <DetailRow icon={<MapPin className="size-4" />} label="Cidade" value={imovel.cidade} />
              <DetailRow icon={<Globe className="size-4" />} label="UF" value={imovel.uf} />
              {imovel.endereco && <DetailRow icon={<Home className="size-4" />} label="Endereço" value={imovel.endereco} />}
            </div>
          </div>

          {/* History */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
              Histórico
            </h2>
            <div className="divide-y divide-[var(--border)]">
              <DetailRow icon={<Clock className="size-4" />} label="Primeira vista" value={formatDate(imovel.data_primeira_vista)} />
              <DetailRow icon={<Clock className="size-4" />} label="Última atualização" value={formatDate(imovel.data_ultima_vista)} />
              <DetailRow icon={<Hash className="size-4" />} label="ID" value={imovel.id} />
            </div>
          </div>

          {/* Description */}
          {imovel.descricao && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
                Descrição
              </h2>
              <p className="text-sm leading-relaxed text-[var(--foreground)]">
                {imovel.descricao}
              </p>
            </div>
          )}

          {/* External Link */}
          <a
            href={imovel.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 w-full rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] px-4 py-3 text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <ExternalLink className="size-4" />
            Ver anúncio original
          </a>
        </div>
      </div>
    </div>
  );
}
