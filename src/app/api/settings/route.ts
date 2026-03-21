import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET() {
  try {
    let settings = await prisma.settings.findUnique({
      where: { id: "global" },
    });

    if (!settings) {
      settings = await prisma.settings.create({
        data: {
          id: "global",
          kokoroUrl: "http://localhost:7860/",
          kokoroVoiceId: "af_heart",
          lmStudioUrl: "http://172.23.48.1:3006/v1",
          lmStudioApiKey: process.env.LM_STUDIO_API_KEY || "",
          unsplashAppId: process.env.UNSPLASH_APP_ID || "",
          unsplashAccessKey: process.env.UNSPLASH_ACCESS_KEY || "",
          unsplashSecretKey: process.env.UNSPLASH_SECRET_KEY || "",
        },
      });
    }

    return NextResponse.json(settings);
  } catch (error) {
    console.error("Failed to fetch settings:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}

export async function PATCH(req: Request) {
  try {
    const body = await req.json();
    const settings = await prisma.settings.upsert({
      where: { id: "global" },
      update: body,
      create: {
        id: "global",
        ...body,
      },
    });
    return NextResponse.json(settings);
  } catch (error) {
    console.error("Failed to update settings:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
