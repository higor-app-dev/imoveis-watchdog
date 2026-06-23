import { NextResponse } from "next/server";
import { getDistinctTipos } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const tipos = await getDistinctTipos();
    return NextResponse.json(tipos);
  } catch (err) {
    console.error("Error fetching tipos:", err);
    return NextResponse.json(
      { error: "Failed to fetch tipos" },
      { status: 500 }
    );
  }
}
