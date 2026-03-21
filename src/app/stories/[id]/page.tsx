import StoryReader from "@/components/StoryReader";

export default async function StoryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StoryReader storyId={id} />;
}
