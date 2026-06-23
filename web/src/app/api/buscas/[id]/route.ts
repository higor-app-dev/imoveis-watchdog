import { NextResponse } from "next/server";
import { getBusca } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const buscaId = Number(id);
    if (isNaN(buscaId)) {
      return NextResponse.json({ error: "Invalid ID" }, { status: 400 });
    }
    const busca = await getBusca(buscaId);
    if (!busca) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }
    return NextResponse.json(busca);
  } catch (err) {
    console.error("Error fetching busca:", err);
    return NextResponse.json({ error: "Failed" }, { status: 500 });
  }
}
