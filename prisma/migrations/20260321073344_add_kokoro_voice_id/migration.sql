-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_Settings" (
    "id" TEXT NOT NULL PRIMARY KEY DEFAULT 'global',
    "lmStudioModelId" TEXT,
    "imageGenProvider" TEXT NOT NULL DEFAULT 'off',
    "imageGenApiKey" TEXT,
    "unsplashAppId" TEXT,
    "unsplashAccessKey" TEXT,
    "unsplashSecretKey" TEXT,
    "kokoroUrl" TEXT NOT NULL DEFAULT 'http://localhost:7860/',
    "kokoroVoiceId" TEXT NOT NULL DEFAULT 'af_heart',
    "lmStudioUrl" TEXT NOT NULL DEFAULT 'http://172.23.48.1:3006/v1',
    "lmStudioApiKey" TEXT,
    "updatedAt" DATETIME NOT NULL
);
INSERT INTO "new_Settings" ("id", "imageGenApiKey", "imageGenProvider", "kokoroUrl", "lmStudioApiKey", "lmStudioModelId", "lmStudioUrl", "unsplashAccessKey", "unsplashAppId", "unsplashSecretKey", "updatedAt") SELECT "id", "imageGenApiKey", "imageGenProvider", "kokoroUrl", "lmStudioApiKey", "lmStudioModelId", "lmStudioUrl", "unsplashAccessKey", "unsplashAppId", "unsplashSecretKey", "updatedAt" FROM "Settings";
DROP TABLE "Settings";
ALTER TABLE "new_Settings" RENAME TO "Settings";
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
