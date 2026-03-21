import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import fs from "fs";
import path from "path";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const story = await prisma.story.findUnique({
      where: { id },
      include: {
        parts: {
          orderBy: { partNumber: "asc" },
          include: {
            segments: {
              orderBy: { segmentOrder: "asc" },
            },
            images: {
              orderBy: { displayTimeMs: "asc" },
            },
          },
        },
        readingProgress: true,
        storyBible: true,
        characters: true,
      },
    });

    if (!story) {
      return NextResponse.json({ error: "Story not found" }, { status: 404 });
    }

    return NextResponse.json(story);
  } catch (error) {
    console.error("Failed to fetch story:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}

export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const body = await req.json();
    
    const story = await prisma.story.update({
      where: { id },
      data: body,
    });

    return NextResponse.json(story);
  } catch (error) {
    console.error("Failed to update story:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;

    // 1. Delete associated files from data directory
    const storyDir = path.join(process.cwd(), "public", "data", "stories", id);
    if (fs.existsSync(storyDir)) {
      fs.rmSync(storyDir, { recursive: true, force: true });
    }

    // 2. Delete from database (Prisma handles cascades if defined, otherwise we do it manually)
    // Based on our schema, we have onDelete: Cascade for StoryPart, Character, Bookmark, ReadingProgress, StoryBible, Image
    // Job has onDelete: SetNull, so we should probably delete jobs too if we want a clean slate
    await prisma.job.deleteMany({
      where: { storyId: id }
    });

    await prisma.story.delete({
      where: { id },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Failed to delete story:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
