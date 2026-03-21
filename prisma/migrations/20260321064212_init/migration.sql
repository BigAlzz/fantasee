-- CreateTable
CREATE TABLE "Story" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "title" TEXT NOT NULL,
    "genre" TEXT NOT NULL,
    "subgenre" TEXT,
    "tonePack" TEXT,
    "description" TEXT,
    "status" TEXT NOT NULL DEFAULT 'draft',
    "plannedParts" INTEGER NOT NULL DEFAULT 1,
    "generatedParts" INTEGER NOT NULL DEFAULT 0,
    "coverImagePath" TEXT,
    "imageMode" TEXT NOT NULL DEFAULT 'off',
    "narratorVoiceId" TEXT,
    "totalDurationSeconds" INTEGER NOT NULL DEFAULT 0,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "StoryPart" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyId" TEXT NOT NULL,
    "partNumber" INTEGER NOT NULL,
    "title" TEXT,
    "summary" TEXT,
    "fullText" TEXT,
    "continuityNotesJson" TEXT,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "audioStatus" TEXT NOT NULL DEFAULT 'pending',
    "imageStatus" TEXT NOT NULL DEFAULT 'pending',
    "mergedAudioPath" TEXT,
    "timingJsonPath" TEXT,
    "durationSeconds" INTEGER NOT NULL DEFAULT 0,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "StoryPart_storyId_fkey" FOREIGN KEY ("storyId") REFERENCES "Story" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "StoryPartSegment" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyPartId" TEXT NOT NULL,
    "segmentOrder" INTEGER NOT NULL,
    "type" TEXT NOT NULL,
    "speakerName" TEXT,
    "text" TEXT NOT NULL,
    "voiceId" TEXT,
    "audioPath" TEXT,
    "startMs" INTEGER,
    "endMs" INTEGER,
    "charStartIndex" INTEGER,
    "charEndIndex" INTEGER,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "StoryPartSegment_storyPartId_fkey" FOREIGN KEY ("storyPartId") REFERENCES "StoryPart" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Character" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "role" TEXT,
    "description" TEXT,
    "traitsJson" TEXT,
    "voiceId" TEXT,
    "firstAppearancePart" INTEGER,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "Character_storyId_fkey" FOREIGN KEY ("storyId") REFERENCES "Story" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Voice" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "provider" TEXT NOT NULL DEFAULT 'kokoro',
    "localVoiceName" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "genderHint" TEXT,
    "ageHint" TEXT,
    "toneTagsJson" TEXT,
    "styleTagsJson" TEXT,
    "active" BOOLEAN NOT NULL DEFAULT true
);

-- CreateTable
CREATE TABLE "Job" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyId" TEXT,
    "partNumber" INTEGER,
    "jobType" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'queued',
    "priority" INTEGER NOT NULL DEFAULT 0,
    "payloadJson" TEXT,
    "resultJson" TEXT,
    "errorText" TEXT,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "startedAt" DATETIME,
    "finishedAt" DATETIME,
    CONSTRAINT "Job_storyId_fkey" FOREIGN KEY ("storyId") REFERENCES "Story" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Bookmark" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyId" TEXT NOT NULL,
    "storyPartId" TEXT NOT NULL,
    "charIndex" INTEGER,
    "audioPositionMs" INTEGER,
    "note" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Bookmark_storyId_fkey" FOREIGN KEY ("storyId") REFERENCES "Story" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "Bookmark_storyPartId_fkey" FOREIGN KEY ("storyPartId") REFERENCES "StoryPart" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "ReadingProgress" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyId" TEXT NOT NULL,
    "currentPartNumber" INTEGER NOT NULL DEFAULT 1,
    "charIndex" INTEGER NOT NULL DEFAULT 0,
    "audioPositionMs" INTEGER NOT NULL DEFAULT 0,
    "fontSize" INTEGER NOT NULL DEFAULT 16,
    "theme" TEXT NOT NULL DEFAULT 'dark',
    "playbackSpeed" REAL NOT NULL DEFAULT 1.0,
    "autoScroll" BOOLEAN NOT NULL DEFAULT true,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "ReadingProgress_storyId_fkey" FOREIGN KEY ("storyId") REFERENCES "Story" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "StoryBible" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyId" TEXT NOT NULL,
    "worldRulesJson" TEXT,
    "plotArcJson" TEXT,
    "endingPlanJson" TEXT,
    "continuityStateJson" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "StoryBible_storyId_fkey" FOREIGN KEY ("storyId") REFERENCES "Story" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Image" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "storyId" TEXT NOT NULL,
    "storyPartId" TEXT,
    "imageType" TEXT NOT NULL,
    "promptText" TEXT NOT NULL,
    "filePath" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Image_storyId_fkey" FOREIGN KEY ("storyId") REFERENCES "Story" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "Image_storyPartId_fkey" FOREIGN KEY ("storyPartId") REFERENCES "StoryPart" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "StoryPart_storyId_partNumber_key" ON "StoryPart"("storyId", "partNumber");

-- CreateIndex
CREATE UNIQUE INDEX "ReadingProgress_storyId_key" ON "ReadingProgress"("storyId");

-- CreateIndex
CREATE UNIQUE INDEX "StoryBible_storyId_key" ON "StoryBible"("storyId");
