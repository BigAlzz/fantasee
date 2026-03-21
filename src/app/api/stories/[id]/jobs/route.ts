import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    
    // Get jobs for the story
    const jobs = await prisma.job.findMany({
      where: { storyId: id },
      orderBy: { createdAt: "desc" },
    });

    // Also get worker heartbeat from global settings
    const settings = await prisma.settings.findUnique({
      where: { id: 'global' },
      select: { workerHeartbeat: true }
    });

    return NextResponse.json({
      jobs,
      workerHeartbeat: settings?.workerHeartbeat || null
    });
  } catch (error) {
    console.error("Failed to fetch jobs for story:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
