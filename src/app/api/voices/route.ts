import { NextResponse } from "next/server";

export async function GET() {
  const voices = [
    { id: "voice_01", label: "Wise Mentor", localVoiceName: "en-US-Wavenet-D", provider: "kokoro", genderHint: "Male", toneTags: ["deep", "slow", "deliberate"] },
    { id: "voice_02", label: "Young Hero", localVoiceName: "en-US-Wavenet-A", provider: "kokoro", genderHint: "Female", toneTags: ["bright", "energetic", "warm"] },
    { id: "voice_03", label: "Narrator Default", localVoiceName: "en-US-Standard-C", provider: "kokoro", genderHint: "Neutral", toneTags: ["calm", "clear"] },
    { id: "voice_04", label: "Villain", localVoiceName: "en-US-Wavenet-B", provider: "kokoro", genderHint: "Male", toneTags: ["calm", "cold", "low-intensity"] },
  ];
  return NextResponse.json(voices);
}
