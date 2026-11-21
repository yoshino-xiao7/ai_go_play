// Refill (roundSnapshots.draftFromRound) restores a round only from its server snapshot.
// Run: node --experimental-strip-types --test tests/round-snapshots.test.ts   (Node 22.12+)
import { test } from "node:test";
import assert from "node:assert/strict";
import { draftFromRound } from "../frontend/src/roundSnapshots.ts";

const frozenRef = {
  id: "ref-1", version_id: "v-first-frame", node_id: "img-1", title: "首帧", role: "first_frame", media_type: "image",
  fit: "cover", purpose: "composition", use_audio: false, crop: { x: 0.1, y: 0.2, width: 0.5, height: 0.6 },
  clip_start: 0, clip_end: null,
};
const audioRef = {
  id: "ref-2", version_id: "v-voice", node_id: "voice-1", title: "配音", role: "reference", media_type: "audio",
  fit: "contain", purpose: "voice", use_audio: true, crop: { x: 0, y: 0, width: 1, height: 1 }, clip_start: 1.5, clip_end: 4.25,
};
const videoJob = (request: Record<string, unknown>) => ({
  id: "job-h3", status: "succeeded", project_id: "p", source_node_id: "vid-1", created_at: "2026-11-21T01:00:00Z", updated_at: "2026-11-21T01:01:00Z",
  outputs: [], request: {
    kind: "video", workflow_id: "builtin-h3-local", prompt: "镜头推近", video_mode: "reference", duration: 7, audio: true,
    video_options: { engine: "native", sampler: "res_multistep", scheduler: "simple", ref_image_size: "1024" },
    references: [frozenRef, audioRef], parameters: { width: 864, height: 480, steps: 20, cfg: 1, seed: 1234, denoise: 1 },
    ...request,
  },
}) as never;
const staleDraft = () => ({
  kind: "video", mode: "text_to_image", prompt: "旧描述", references: [], frame_count: 22, duration: 4,
  parameters: { width: 1344, height: 768, steps: 99, cfg: 7, seed: 5 },
  pending_submission: { request_id: "old-request" }, pending_request_id: "old-request",
}) as never;

test("H3 refill restores the snapshot's exact frame_count, not the draft's", () => {
  const draft = draftFromRound(videoJob({ frame_count: 124 }), staleDraft(), "vid-1", { seed: "same" });
  assert.equal(draft.frame_count, 124);
  assert.equal(draft.duration, 7);
});

test("an older snapshot without frame_count does not inherit another round's frame count", () => {
  const draft = draftFromRound(videoJob({}), staleDraft(), "vid-1", { seed: "same" });
  assert.equal(draft.frame_count, undefined);
  assert.ok("frame_count" in draft, "the key is set explicitly so the stale value is cleared");
});

test("video references keep fit, purpose, use_audio, crop, clip_start and clip_end", () => {
  const draft = draftFromRound(videoJob({ frame_count: 124 }), staleDraft(), "vid-1", { seed: "same" });
  for (const [restored, frozen] of [[draft.references[0], frozenRef], [draft.references[1], audioRef]] as const)
    for (const key of ["fit", "purpose", "use_audio", "crop", "clip_start", "clip_end"] as const)
      assert.deepEqual(restored[key], frozen[key], `${frozen.version_id}.${key}`);
  assert.equal(draft.references[0].clip_end, null);
  assert.deepEqual(draft.references.map(ref => ref.source), ["mention", "mention"]);
  assert.deepEqual(draft.reference_order, ["v-first-frame", "v-voice"]);
});

test("refill deep-copies: editing the draft never touches the job snapshot", () => {
  const job = videoJob({ frame_count: 124, h3_guides: [{ version_id: "g", media_type: "image", frame_idx: 3 }] });
  const before = JSON.stringify(job);
  const draft = draftFromRound(job, staleDraft(), "vid-1", { seed: "same" });
  draft.references[0].crop!.x = 0.9;
  draft.video_options!.engine = "turbo";
  draft.h3_guides![0].frame_idx = 9;
  draft.parameters.steps = 50;
  assert.equal(JSON.stringify(job), before);
});

test("parameters come only from the snapshot", () => {
  const job = videoJob({ parameters: { width: 864, height: 480, seed: 1234 } });
  const draft = draftFromRound(job, staleDraft(), "vid-1", { seed: "same" });
  assert.deepEqual(draft.parameters, { width: 864, height: 480, seed: 1234 });
});

test("refill clears both halves of an earlier unconfirmed submission", () => {
  const draft = draftFromRound(videoJob({ frame_count: 124 }), staleDraft(), "vid-1", { seed: "same" });
  assert.equal(draft.pending_submission, undefined);
  assert.equal(draft.pending_request_id, undefined);
  assert.equal(draft.refill_of?.job_id, "job-h3");
});

test("seed: same keeps the resolved seed, random asks for a new one", () => {
  assert.equal(draftFromRound(videoJob({}), staleDraft(), "vid-1", { seed: "same" }).parameters.seed, 1234);
  const random = draftFromRound(videoJob({}), staleDraft(), "vid-1", { seed: "random" });
  assert.equal(random.parameters.seed, -1);
  assert.equal(random.refill_of?.seed, 1234);
});

test("image edit refill keeps the base image out of the extra references", () => {
  const job = {
    id: "job-img", status: "succeeded", project_id: "p", source_node_id: "img-1", created_at: "t", updated_at: "t", outputs: [],
    request: { workflow_id: "w", prompt: "改成雨夜", negative_prompt: "", parameters: { width: 1024, height: 576, seed: 7 },
      references: [{ version_id: "base", node_id: "img-1", title: "底图" }, { version_id: "extra", node_id: "other", title: "参考" }] },
  } as never;
  const draft = draftFromRound(job, undefined, "img-1", { seed: "same", workflowMode: "edit" });
  assert.equal(draft.edit_base_version_id, "base");
  assert.deepEqual(draft.references.map(ref => ref.version_id), ["extra"]);
  assert.deepEqual(draft.reference_order, ["base", "extra"]);
  assert.equal(draft.parameters.negative_prompt, "");
});
