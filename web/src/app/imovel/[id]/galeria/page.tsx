"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ImageIcon,
  Grid3X3,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useImovel } from "@/hooks/useImovel";

function Loading() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <div className="animate-pulse text-[var(--muted-foreground)]">Carregando...</div>
    </div>
  );
}

export default function GaleriaPage() {
  const params = useParams();
  const id = decodeURIComponent(params.id as string);
  const { imovel, loading, error } = useImovel(id);
  const [lightbox, setLightbox] = useState<number | null>(null);

  // Build image list
  const images: string[] = (() => {
    if (!imovel) return [];
    if (imovel.fotos) {
      try {
        const parsed = JSON.parse(imovel.fotos);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      } catch {}
    }
    return imovel.foto_url ? [imovel.foto_url] : [];
  })();

  const title =
    imovel?.titulo ||
    `${imovel?.bairro ?? ""}${imovel?.cidade ? `, ${imovel.cidade}` : ""}`;

  if (loading) return <Loading />;

  if (!imovel) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-16 text-center">
        <h1 className="text-xl font-bold mb-2">
          {error ? "Erro ao carregar" : "Imóvel não encontrado"}
        </h1>
        {error && <p className="text-sm text-red-500 mb-2">{error}</p>}
        <Link href="/" className="text-sm text-[var(--primary)] hover:underline">
          ← Voltar ao início
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <Link
            href={`/imovel/${encodeURIComponent(id)}`}
            className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-bold truncate">Galeria de Fotos</h1>
            <p className="text-sm text-[var(--muted-foreground)] truncate">
              {title} · {images.length} {images.length === 1 ? "foto" : "fotos"}
            </p>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] shrink-0">
            <Grid3X3 className="size-4" />
            <span>{images.length}</span>
          </div>
        </div>

        {/* Gallery — single column, full width */}
        {images.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] p-16 text-center">
            <ImageIcon className="size-16 mx-auto mb-3 opacity-30 text-[var(--muted-foreground)]" />
            <p className="text-sm text-[var(--muted-foreground)]">
              Nenhuma foto disponível
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {images.map((url, i) => (
              <button
                key={i}
                onClick={() => setLightbox(i)}
                className="group relative w-full rounded-xl overflow-hidden border border-[var(--border)] bg-[var(--muted)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              >
                <img
                  src={url}
                  alt={`${title} - foto ${i + 1}`}
                  className="w-full h-auto block group-hover:scale-[1.02] transition-transform duration-300"
                  loading="lazy"
                />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors pointer-events-none" />
                <div className="absolute bottom-3 right-3 bg-black/50 text-white text-xs px-2 py-1 rounded-full backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                  {i + 1}/{images.length}
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Back link */}
        <div className="mt-8 text-center">
          <Link
            href={`/imovel/${encodeURIComponent(id)}`}
            className="inline-flex items-center gap-1.5 text-sm text-[var(--primary)] hover:underline"
          >
            <ArrowLeft className="size-4" />
            Voltar ao imóvel
          </Link>
        </div>
      </div>

      {/* Lightbox */}
      {lightbox !== null && (
        <div
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
          onClick={() => setLightbox(null)}
        >
          <button
            onClick={() => setLightbox(null)}
            className="absolute top-4 right-4 size-10 flex items-center justify-center rounded-full bg-black/40 text-white hover:bg-black/60 transition-colors backdrop-blur-sm"
            aria-label="Fechar"
          >
            <X className="size-6" />
          </button>

          <div className="absolute top-4 left-4 bg-black/50 text-white text-sm px-3 py-1 rounded-full backdrop-blur-sm">
            {lightbox + 1} / {images.length}
          </div>

          {images.length > 1 && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setLightbox((lightbox - 1 + images.length) % images.length);
              }}
              className="absolute left-4 top-1/2 -translate-y-1/2 size-12 flex items-center justify-center rounded-full bg-black/40 text-white hover:bg-black/60 transition-colors backdrop-blur-sm"
              aria-label="Anterior"
            >
              <ChevronLeft className="size-7" />
            </button>
          )}

          <img
            src={images[lightbox]}
            alt={`${title} - foto ${lightbox + 1}`}
            className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />

          {images.length > 1 && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setLightbox((lightbox + 1) % images.length);
              }}
              className="absolute right-4 top-1/2 -translate-y-1/2 size-12 flex items-center justify-center rounded-full bg-black/40 text-white hover:bg-black/60 transition-colors backdrop-blur-sm"
              aria-label="Próxima"
            >
              <ChevronRight className="size-7" />
            </button>
          )}

          {images.length > 3 && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-2 max-w-[80vw] overflow-x-auto px-2 py-2 rounded-full bg-black/30 backdrop-blur-sm">
              {images.map((url, i) => (
                <button
                  key={i}
                  onClick={(e) => {
                    e.stopPropagation();
                    setLightbox(i);
                  }}
                  className={`shrink-0 size-12 rounded-lg overflow-hidden border-2 transition-all ${
                    i === lightbox
                      ? "border-white scale-110"
                      : "border-transparent opacity-50 hover:opacity-80"
                  }`}
                >
                  <img src={url} alt="" className="size-full object-cover" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
