import { NextResponse } from "next/server";
import { listBuscas } from "@/lib/turso";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const buscas = await listBuscas();
    return NextResponse.json(buscas);
  } catch (err) {
    console.error("Error listing buscas:", err);
    return NextResponse.json(
      { error: "Failed to list buscas" },
      { status: 500 }
    );
  }
}
