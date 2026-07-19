import test from "node:test";
import assert from "node:assert/strict";

import { projectProductionActivity } from "../src/productionActivity.ts";

test("projects one truthful role for a working library child instead of duplicating its parent", () => {
  const projection = projectProductionActivity(
    [
      {
        id: "library-123",
        kind: "library_maintenance",
        status: "running",
        stage: "regenerate",
        progress: 0.2,
        message: "3/10: Re-generating the story",
      },
      {
        id: "library-123-02",
        parent: "library-123",
        kind: "library_story",
        story_id: "alien-signal",
        title: "The Alien Signal",
        status: "running",
        stage: "regenerate",
        progress: 0.5,
        message: "Re-generating the alien signal",
      },
    ],
    [
      {
        id: "maintenance-19600",
        capabilities: ["cpu", "gpu"],
        status: "running",
        current_job_id: "library-123-02",
      },
    ],
  );

  assert.equal(projection.activities.length, 1);
  assert.deepEqual(projection.activities[0], {
    id: "library-123-02",
    role: "Task librarian",
    stage: "Regenerate",
    story: "The Alien Signal",
    message: "Re-generating the alien signal",
    progress: 0.5,
    status: "running",
    workerId: "maintenance-19600",
  });
  assert.equal(projection.onlineWorkers, 1);
  assert.equal(projection.workingRoles, 1);
});

test("maps bounded generation work to the role named by its real stage or message", () => {
  const projection = projectProductionActivity(
    [
      {
        id: "generation-1",
        kind: "generate",
        status: "running",
        stage: "generate",
        progress: 0.42,
        message: "Art director is planning scene illustrations",
        request: { story_concept: "A signal reaches Johannesburg" },
      },
    ],
    [],
  );

  assert.equal(projection.activities.length, 1);
  assert.equal(projection.activities[0].role, "Art director");
  assert.equal(projection.activities[0].story, "A signal reaches Johannesburg");
  assert.equal(projection.workingRoles, 1);
});

test("does not light stale queue records that have no online worker lease", () => {
  const projection = projectProductionActivity(
    [
      {
        id: "library-old",
        kind: "library_maintenance",
        status: "running",
        stage: "regenerate",
        progress: 0.05,
        message: "Recovered library maintenance",
      },
      {
        id: "library-old-01",
        parent: "library-old",
        kind: "library_story",
        story_id: "old-story",
        status: "running",
        stage: "queued",
        progress: 0,
        message: "running",
      },
      {
        id: "library-finished",
        kind: "library_maintenance",
        status: "error",
        progress: 1,
        message: "failed",
      },
      {
        id: "library-finished-01",
        parent: "library-finished",
        kind: "library_story",
        story_id: "orphaned-story",
        status: "running",
        stage: "queued",
        progress: 0,
        message: "running",
      },
    ],
    [],
  );

  assert.deepEqual(projection.activities, []);
  assert.equal(projection.workingRoles, 0);
});
