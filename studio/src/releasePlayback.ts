import type { ProductionRelease } from "./api";

export function selectPlayableRelease(releases: ProductionRelease[]): ProductionRelease | undefined {
  return releases.find((release) => release.status === "current") ?? releases[0];
}
