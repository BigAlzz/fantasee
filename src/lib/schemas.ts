import { z } from "zod";

export const StoryCreateSchema = z.object({
  title: z.string().optional(),
  genre: z.string(),
  subgenre: z.string().optional(),
  tonePack: z.string().optional(),
  description: z.string().optional(),
  plannedParts: z.number().int().min(1).max(1000).default(3),
  imageMode: z.enum(["off", "cover_only", "chapter_art", "scene_art"]).default("off"),
  narratorVoiceId: z.string().optional(),
  endingMode: z.enum(["tight", "open", "expandable", "series", "unending"]).default("tight"),
  premise: z.string().optional(),
  seriesType: z.enum(["standalone", "trilogy", "saga"]).default("standalone"),
});

export type StoryCreateInput = z.infer<typeof StoryCreateSchema>;

export const JobStatusSchema = z.object({
  status: z.enum(["queued", "running", "done", "failed", "canceled"]),
});
