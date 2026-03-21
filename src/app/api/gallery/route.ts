import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import fs from "fs";
import path from "path";

export async function GET() {
  try {
    const images = await prisma.image.findMany({
      orderBy: { createdAt: "desc" },
      include: {
        story: {
          select: { title: true, id: true }
        }
      }
    });

    const stories = await prisma.story.findMany({
      where: { status: 'complete' },
      select: { id: true, title: true, parts: { select: { mergedAudioPath: true, partNumber: true }, orderBy: { partNumber: 'asc' } } }
    });

    return NextResponse.json({ images, stories });
  } catch (error) {
    console.error("Failed to fetch gallery images:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}

export async function DELETE() {
  try {
    const images = await prisma.image.findMany({
      orderBy: { createdAt: "desc" }
    });

    const seenSizes = new Map<number, string>();
    const toDeleteIds: string[] = [];

    for (const img of images) {
      const fullPath = path.join(process.cwd(), "public", img.filePath.replace(/^\//, ""));
      if (fs.existsSync(fullPath)) {
        const stats = fs.statSync(fullPath);
        const size = stats.size;
        
        if (seenSizes.has(size)) {
          // It's a duplicate (likely)
          toDeleteIds.push(img.id);
        } else {
          seenSizes.set(size, img.id);
        }
      } else {
        // Missing file? Still delete from DB
        toDeleteIds.push(img.id);
      }
    }

    if (toDeleteIds.length > 0) {
      await prisma.image.deleteMany({
        where: { id: { in: toDeleteIds } }
      });
    }

    return NextResponse.json({ 
      success: true, 
      cleanedCount: toDeleteIds.length 
    });
  } catch (error) {
    console.error("Gallery cleanup failed:", error);
    return NextResponse.json({ error: "Cleanup failed" }, { status: 500 });
  }
}
