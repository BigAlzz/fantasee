-- CreateTable
CREATE TABLE "Settings" (
    "id" TEXT NOT NULL PRIMARY KEY DEFAULT 'global',
    "lmStudioModelId" TEXT,
    "imageGenProvider" TEXT NOT NULL DEFAULT 'off',
    "imageGenApiKey" TEXT,
    "unsplashAccessKey" TEXT,
    "kokoroUrl" TEXT NOT NULL DEFAULT 'http://localhost:7860/',
    "lmStudioUrl" TEXT NOT NULL DEFAULT 'http://172.23.48.1:3006/v1',
    "lmStudioApiKey" TEXT,
    "updatedAt" DATETIME NOT NULL
);
