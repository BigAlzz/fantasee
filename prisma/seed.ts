import { PrismaClient } from "@prisma/client";
import "dotenv/config";

const prisma = new PrismaClient();

async function main() {
  const voices = [
    {
      localVoiceName: "en-US-Wavenet-D",
      label: "Wise Mentor",
      provider: "kokoro",
      genderHint: "Male",
      toneTagsJson: JSON.stringify(["deep", "slow", "deliberate"]),
    },
    {
      localVoiceName: "en-US-Wavenet-A",
      label: "Young Hero",
      provider: "kokoro",
      genderHint: "Female",
      toneTagsJson: JSON.stringify(["bright", "energetic", "warm"]),
    },
    {
      localVoiceName: "en-US-Standard-C",
      label: "Narrator Default",
      provider: "kokoro",
      genderHint: "Neutral",
      toneTagsJson: JSON.stringify(["calm", "clear"]),
    },
    {
      localVoiceName: "en-US-Wavenet-B",
      label: "Villain",
      provider: "kokoro",
      genderHint: "Male",
      toneTagsJson: JSON.stringify(["calm", "cold", "low-intensity"]),
    },
  ];

  for (const voice of voices) {
    await prisma.voice.upsert({
      where: { localVoiceName: voice.localVoiceName },
      update: voice,
      create: voice,
    });
  }

  console.log("Seed data created successfully");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
