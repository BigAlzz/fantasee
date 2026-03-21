import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function POST() {
  try {
    // Update all failed and stuck jobs to 'queued'
    const result = await prisma.job.updateMany({
      where: {
        status: { in: ['failed', 'running'] }
      },
      data: {
        status: 'queued',
        attempts: 0,
        errorText: null,
        startedAt: null,
        finishedAt: null
      }
    });

    // Also ensure stories are in 'generating' state if they have queued jobs
    const queuedJobs = await prisma.job.findMany({
      where: { status: 'queued' },
      select: { storyId: true },
      distinct: ['storyId']
    });

    if (queuedJobs.length > 0) {
      await prisma.story.updateMany({
        where: {
          id: { in: queuedJobs.map(j => j.storyId) },
          status: { not: 'generating' }
        },
        data: { status: 'generating' }
      });
    }

    return NextResponse.json({ 
      success: true, 
      count: result.count 
    });
  } catch (error) {
    console.error("Failed to retry jobs:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
