import { NextResponse } from "next/server";

export async function GET() {
  const genres = {
    core: [
      "Fantasy", "Epic Fantasy", "Dark Fantasy", "Urban Fantasy", "Fairy Tale", "Mythic Adventure",
      "Science Fiction", "Space Opera", "Cyberpunk", "Steampunk", "Dystopian", "Post-Apocalyptic", "Time Travel",
      "Mystery", "Detective", "Thriller", "Psychological Thriller",
      "Horror", "Gothic Horror", "Paranormal",
      "Adventure", "Action", "Historical Fiction", "Alternate History",
      "Romance", "Romantic Comedy", "Drama", "Literary Fiction", "Young Adult", "Coming of Age", "Comedy", "Satire",
      "Non-Fiction", "Biography", "Self-Help", "History", "Science", "Philosophy", "Erotic", "XXX"
    ],
    lighter: [
      "Bedtime Story", "Children’s Adventure", "Animal Tale", "Educational Story", "Magical School", "Cozy Village Tale", "Folklore Inspired"
    ],
    erotic: [
      "Erotic Romance", "Dark Erotica", "Sensual Drama", "Steam", "BDSM", "Taboo", "Adult Fantasy", "XXX"
    ],
    non_fiction: [
      "Scientific Discovery", "Historical Account", "Biographical Sketch", "Philosophical Treatise", "Self-Improvement Guide", "Technical Explainer"
    ],
    regional: [
      "African Fantasy", "Afrofuturism", "Township Mystery", "Johannesburg Magic", "Karoo Ghost Story", "Futuristic African City",
      "Pirate Adventure", "Treasure Hunt", "Court Intrigue", "Survival Tale", "Monster Hunt", "Superhero"
    ]
  };
  return NextResponse.json(genres);
}
