import assert from "node:assert/strict";
import test from "node:test";
import { selectPlayableRelease } from "../src/releasePlayback.ts";

const release = (id: string, status: string) => ({
  id,
  story_id: "story",
  release_type: "plex",
  fingerprint: id,
  status,
  path: `C:\\releases\\${id}`,
  created_at: 1,
});

test("canonical playback selects the current durable release", () => {
  const historical = release("old", "superseded");
  const current = release("current", "current");

  assert.equal(selectPlayableRelease([historical, current])?.id, "current");
});

test("playback falls back to the newest available release when status is missing", () => {
  assert.equal(selectPlayableRelease([release("latest", "unknown")])?.id, "latest");
  assert.equal(selectPlayableRelease([]), undefined);
});
