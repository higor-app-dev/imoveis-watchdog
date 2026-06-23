import { NextResponse } from "next/server";
import { getDistinctFontes } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
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
