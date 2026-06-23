import { NextRequest, NextResponse } from "next/server";
import { listImoveis, type ImovelFilters } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const filters: ImovelFilters = {
      bairro: searchParams.get("bairro") || undefined,
      tipo: searchParams.get("tipo") || undefined,
      modalidade: searchParams.get("modalidade") || undefined,
      cidade: searchParams.get("cidade") || undefined,
      fonte: searchParams.get("fonte") || undefined,
      preco_max: searchParams.get("preco_max")
        ? Number(searchParams.get("preco_max"))
        : undefined,
      preco_min: searchParams.get("preco_min")
        ? Number(searchParams.get("preco_min"))
        : undefined,
      area_min: searchParams.get("area_min")
        ? Number(searchParams.get("area_min"))
        : undefined,
      quartos_min: searchParams.get("quartos_min")
        ? Number(searchParams.get("quartos_min"))
        : undefined,
      vagas_min: searchParams.get("vagas_min")
        ? Number(searchParams.get("vagas_min"))
        : undefined,
      sort: (searchParams.get("sort") as "data" | "preco" | "area") || undefined,
      order: (searchParams.get("order") as "asc" | "desc") || undefined,
      limit: searchParams.get("limit")
        ? Number(searchParams.get("limit"))
        : 50,
      offset: searchParams.get("offset")
        ? Number(searchParams.get("offset"))
        : 0,
    };

    const result = await listImoveis(filters);
    return NextResponse.json(result);
  } catch (err) {
    console.error("Error listing imoveis:", err);
    return NextResponse.json(
      { error: "Failed to list imoveis" },
      { status: 500 }
    );
  }
}
