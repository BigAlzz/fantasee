/*
  Warnings:

  - A unique constraint covering the columns `[localVoiceName]` on the table `Voice` will be added. If there are existing duplicate values, this will fail.

*/
-- CreateIndex
CREATE UNIQUE INDEX "Voice_localVoiceName_key" ON "Voice"("localVoiceName");
