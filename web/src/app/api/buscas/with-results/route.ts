import { NextResponse } from "next/server";
import { listBuscasComResultados } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const buscas = await listBuscasComResultados();
    return NextResponse.json(buscas);
  } catch (err) {
    console.error("Error listing buscas with results:", err);
    return NextResponse.json(
      { error: "Failed to list buscas" },
      { status: 500 }
    );
  }
}
