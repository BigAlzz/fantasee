import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const { concept } = await req.json();

    // 1. Update the story with the chosen title and description
    const story = await prisma.story.update({
      where: { id },
      data: {
        title: concept.title,
        description: concept.blurb,
        status: "generating",
      },
    });

    // 2. Queue the story bible job
    await prisma.job.create({
      data: {
        storyId: story.id,
        jobType: "build_story_bible",
        priority: 9,
        payloadJson: JSON.stringify({
          concept: {
            title: concept.title,
            blurb: concept.blurb,
          },
          plannedParts: story.plannedParts,
        }),
      },
    });

    return NextResponse.json({ status: "success" });
  } catch (error) {
    console.error("Failed to select concept:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
