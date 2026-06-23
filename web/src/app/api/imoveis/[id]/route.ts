import { NextRequest, NextResponse } from "next/server";
import { listImoveis } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    if (!id) {
      return NextResponse.json({ error: "Missing imovel ID" }, { status: 400 });
    }

    const result = await listImoveis({ id, limit: 1, offset: 0 });
    const imovel = result.imoveis[0] ?? null;

    if (!imovel) {
      return NextResponse.json({ error: "Imóvel not found" }, { status: 404 });
    }

    return NextResponse.json(imovel);
  } catch (err) {
    console.error("Error fetching imovel:", err);
    return NextResponse.json(
      { error: "Failed to fetch imovel" },
      { status: 500 }
    );
  }
}
