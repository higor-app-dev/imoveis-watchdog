import { NextRequest, NextResponse } from "next/server";
import { getDistinctFontes, getDistinctFontesPorBusca } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const buscaIdParam = searchParams.get("busca_id");

    if (buscaIdParam) {
      const buscaId = Number(buscaIdParam);
      if (isNaN(buscaId)) {
        return NextResponse.json({ error: "Invalid busca_id" }, { status: 400 });
      }
      const fontes = await getDistinctFontesPorBusca(buscaId);
      return NextResponse.json(fontes);
    }

    const fontes = await getDistinctFontes();
    return NextResponse.json(fontes);
  } catch (err) {
    console.error("Error fetching fontes:", err);
    return NextResponse.json(
      { error: "Failed to fetch fontes" },
      { status: 500 }
    );
  }
}
