import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET() {
  try {
    // Get all jobs across all stories, ordered by most recent
    const jobs = await prisma.job.findMany({
      orderBy: { createdAt: "desc" },
      take: 50, // Limit to recent 50 jobs for global view
    });

    // Get worker heartbeat from global settings
    const settings = await prisma.settings.findUnique({
      where: { id: 'global' },
      select: { workerHeartbeat: true }
    });

    return NextResponse.json({
      jobs,
      workerHeartbeat: settings?.workerHeartbeat || null
    });
  } catch (error) {
    console.error("Failed to fetch global jobs:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
