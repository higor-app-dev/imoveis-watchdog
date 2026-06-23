import { NextRequest, NextResponse } from "next/server";
import { getBusca, listImoveis, type ImovelFilters } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const buscaId = Number(id);
    if (isNaN(buscaId)) {
      return NextResponse.json({ error: "Invalid busca ID" }, { status: 400 });
    }

    const busca = await getBusca(buscaId);
    if (!busca) {
      return NextResponse.json({ error: "Busca not found" }, { status: 404 });
    }

    const { searchParams } = new URL(_request.url);
    const filters: ImovelFilters = {
      busca_id: buscaId,
      bairro: searchParams.get("bairro") || undefined,
      tipo: searchParams.get("tipo") || undefined,
      modalidade: searchParams.get("modalidade") || undefined,
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
      limit: searchParams.get("limit")
        ? Number(searchParams.get("limit"))
        : 100,
      offset: searchParams.get("offset")
        ? Number(searchParams.get("offset"))
        : 0,
    };

    const result = await listImoveis(filters);
    return NextResponse.json({ busca, ...result });
  } catch (err) {
    console.error("Error fetching busca imoveis:", err);
    return NextResponse.json(
      { error: "Failed to fetch imoveis" },
      { status: 500 }
    );
  }
}
