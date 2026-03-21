import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const { additionalParts } = await req.json();
    
    if (!additionalParts || additionalParts < 1) {
      return NextResponse.json({ error: "Invalid parts count" }, { status: 400 });
    }

    const story = await prisma.story.findUnique({
      where: { id },
      include: { parts: true }
    });

    if (!story) {
      return NextResponse.json({ error: "Story not found" }, { status: 404 });
    }

    const currentPlanned = story.plannedParts || 0;
    const currentActualParts = story.parts.length;
    const nextPartNumber = currentActualParts + 1;
    const newPlannedTotal = currentPlanned + additionalParts;

    // 1. Update story planned parts
    await prisma.story.update({
      where: { id },
      data: { 
        plannedParts: newPlannedTotal,
        status: 'generating'
      }
    });

    // 2. Queue the next part generation job
    await prisma.job.create({
      data: {
        id: `${id}_part${nextPartNumber}`,
        storyId: id,
        partNumber: nextPartNumber,
        jobType: 'generate_part',
        status: 'queued',
        priority: 8,
      }
    });

    return NextResponse.json({ success: true, newPlannedTotal });
  } catch (error) {
    console.error("Failed to extend story:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
