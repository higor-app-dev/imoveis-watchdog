import { NextResponse } from "next/server";
import { getDistinctBairros } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const bairros = await getDistinctBairros();
    return NextResponse.json(bairros);
  } catch (err) {
    console.error("Error fetching bairros:", err);
    return NextResponse.json(
      { error: "Failed to fetch bairros" },
      { status: 500 }
    );
  }
}
