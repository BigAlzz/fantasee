import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { StoryCreateSchema } from "@/lib/schemas";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const validatedData = StoryCreateSchema.parse(body);

    let seriesId = null;
    let seriesOrder = null;

    // Handle Series Creation
    if (validatedData.seriesType === "trilogy" || validatedData.seriesType === "saga") {
      const series = await prisma.series.create({
        data: {
          title: validatedData.title ? `${validatedData.title} (Series)` : "New Series",
          description: validatedData.description || validatedData.premise,
          status: "active",
        }
      });
      seriesId = series.id;
      seriesOrder = 1;
    }

    // 1. Create the story draft
    const story = await prisma.story.create({
      data: {
        title: validatedData.title || "Untitled Story",
        genre: validatedData.genre,
        subgenre: validatedData.subgenre,
        tonePack: validatedData.tonePack,
        description: validatedData.description || validatedData.premise,
        plannedParts: validatedData.plannedParts,
        imageMode: validatedData.imageMode,
        narratorVoiceId: validatedData.narratorVoiceId,
        status: "draft",
        seriesId: seriesId,
        seriesOrder: seriesOrder,
      },
    });

    // 2. Initialize reading progress
    await prisma.readingProgress.create({
      data: {
        storyId: story.id,
      },
    });

    // 3. Queue jobs based on if a title was provided
    if (!validatedData.title || validatedData.title.trim() === "") {
      // Need concepts
      await prisma.job.create({
        data: {
          storyId: story.id,
          jobType: "generate_concepts",
          priority: 10,
          payloadJson: JSON.stringify({
            genre: validatedData.genre,
            subgenre: validatedData.subgenre,
            tonePack: validatedData.tonePack,
            premise: validatedData.premise,
          }),
        },
      });
    } else {
      // Start generating story bible then part 1
      await prisma.job.create({
        data: {
          storyId: story.id,
          jobType: "build_story_bible",
          priority: 9,
          payloadJson: JSON.stringify({
            concept: {
              title: validatedData.title,
              blurb: validatedData.description || validatedData.premise,
            },
            plannedParts: validatedData.plannedParts,
            endingMode: validatedData.endingMode,
          }),
        },
      });
      
      // Update status to generating
      await prisma.story.update({
        where: { id: story.id },
        data: { status: "generating" },
      });
    }

    return NextResponse.json(story, { status: 201 });
  } catch (error: any) {
    console.error("Failed to create story:", error);
    if (error.name === "ZodError") {
      return NextResponse.json({ error: error.errors }, { status: 400 });
    }
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}

export async function GET() {
  try {
    const stories = await prisma.story.findMany({
      orderBy: { createdAt: "desc" },
      include: {
        _count: {
          select: { parts: true }
        },
        series: {
          select: { id: true, title: true }
        },
        parts: {
          orderBy: { partNumber: "asc" },
          select: { 
            id: true,
            partNumber: true,
            title: true,
            summary: true,
            mergedAudioPath: true
          }
        },
        fullAudioPath: true,
        videoPath: true
      },
    });
    return NextResponse.json(stories);
  } catch (error) {
    console.error("Failed to fetch stories:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
