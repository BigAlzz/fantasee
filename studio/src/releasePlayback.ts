import type { ProductionRelease } from "./api";

export function selectPlayableRelease(releases: ProductionRelease[]): ProductionRelease | undefined {
  return releases.find((release) => release.status === "current") ?? releases[0];
}

export type PlaybackTarget =
  | { kind: "release"; release: ProductionRelease }
  | { kind: "canonical" };

/**
 * Recorded releases were introduced after the first library was generated.
 * Completed legacy stories can still have a verified canonical MP4 without a
 * production_releases row, so playback must retain that safe fallback.
 */
export function selectPlaybackTarget(
  releases: ProductionRelease[],
  canonicalVideoReady: boolean,
): PlaybackTarget | undefined {
  const release = selectPlayableRelease(releases);
  if (release) return { kind: "release", release };
  return canonicalVideoReady ? { kind: "canonical" } : undefined;
}
