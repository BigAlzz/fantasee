import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET() {
  try {
    const settings = await prisma.settings.findUnique({
      where: { id: "global" },
    });

    const lmUrl = settings?.lmStudioUrl || "http://172.23.48.1:3006/v1";
    const apiKey = settings?.lmStudioApiKey || process.env.LM_STUDIO_API_KEY || "";

    console.log(`Fetching models from: ${lmUrl}/models`);

    const response = await fetch(`${lmUrl.replace(/\/$/, "")}/models`, {
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      cache: 'no-store'
    });

    if (!response.ok) {
      throw new Error(`LM Studio returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error("Failed to fetch LM Studio models:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
