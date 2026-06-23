import { NextRequest, NextResponse } from "next/server";
import { getImoveisRecentes } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(
      Number(searchParams.get("limit") ?? 20),
      100
    );
    const imoveis = await getImoveisRecentes(limit);
    return NextResponse.json({ imoveis, total: imoveis.length });
  } catch (err) {
    console.error("Error fetching recent imoveis:", err);
    return NextResponse.json(
      { error: "Failed to fetch recent imoveis" },
      { status: 500 }
    );
  }
}
