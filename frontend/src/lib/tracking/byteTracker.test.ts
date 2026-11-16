import { describe, expect, it } from "vitest";
import { ByteTracker, DEFAULT_TRACKER_CONFIG, type TrackerDetection } from "./byteTracker";
import { kalmanFilter } from "./kalmanFilter";
import { linearAssignment } from "./linearAssignment";
import { TrackerHost } from "./trackerHost";

const config = { ...DEFAULT_TRACKER_CONFIG, confidence: 0.25, lowScoreFloor: 0.1 };

function car(x: number, confidence = 0.9, y = 100): TrackerDetection {
  return { classId: 2, confidence, box: [x, y, x + 60, y + 40] };
}

function ids(tracker: ByteTracker, detections: TrackerDetection[]): (number | null)[] {
  return tracker.update(detections).objects.map((object) => object.trackId);
}

describe("Kalman filter (parity with Ultralytics KalmanFilterXYAH)", () => {
  it("reproduces initiate, predict, update, predict exactly", () => {
    let state = kalmanFilter.initiate([100, 50, 0.5, 80]);
    state = kalmanFilter.predict(state);
    state = kalmanFilter.update(state, [104, 47, 0.52, 82]);
    state = kalmanFilter.predict(state);
    // Reference values computed with ultralytics 8.4.207 (NumPy float64).
    const mean = [104.29752066115702, 46.77685950413223, 0.5003921572510572, 82.14876033057851, 0.8264462809917356,
      -0.6198347107438017, 1.9607842945021166e-10, 0.4132231404958678];
    const diagonal = [57.282323611775155, 57.282323611775155, 0.0002960789235678547, 57.282323611775155,
      20.34567551097944, 20.34567551097944, 2.999999990196079e-10, 20.34567551097944];
    state.mean.forEach((value, i) => expect(value).toBeCloseTo(mean[i], 9));
    diagonal.forEach((value, i) => expect(state.covariance[i][i]).toBeCloseTo(value, 9));
    expect(state.covariance[0][4]).toBeCloseTo(23.390495867768593, 9);
    expect(state.covariance[3][7]).toBeCloseTo(23.390495867768593, 9);
  });
});

describe("linear assignment (parity with lap.lapjv, extend_cost=True, cost_limit)", () => {
  // Cases and expected matches computed with lap 0.5.12.
  const cases: { cost: number[][]; limit: number; matches: [number, number][] }[] = [
    { cost: [[0.6250954866409302, 0.8972138166427612, 0.7756856679916382, 0.22520719468593597],
      [0.3001662790775299, 0.873553454875946, 0.0052653043530881405, 0.8212284445762634],
      [0.7970694303512573, 0.4679349660873413, 0.30303242802619934, 0.2784256041049957]],
    limit: 0.8, matches: [[0, 3], [1, 2], [2, 1]] },
    { cost: [[0.25486958026885986, 0.4450763165950775], [0.5045482516288757, 0.5534973740577698],
      [0.9955002665519714, 0.7926619052886963], [0.6221792101860046, 0.9889601469039917],
      [0.21530869603157043, 0.16021203994750977]], limit: 0.5, matches: [[0, 0], [4, 1]] },
    { cost: [[0.6125395894050598, 0.043942008167505264, 0.03568027913570404, 0.5148888230323792],
      [0.46620601415634155, 0.9171677827835083, 0.6292262673377991, 0.5141176581382751],
      [0.4968734383583069, 0.24751491844654083, 0.01179402507841587, 0.19240213930606842],
      [0.6920320987701416, 0.20060671865940094, 0.36953631043434143, 0.0037342419382184744]],
    limit: 0.7, matches: [[0, 1], [1, 0], [2, 2], [3, 3]] },
    { cost: [[0.8300477266311646, 0.1544610857963562, 0.26759931445121765, 0.8803321719169617, 0.50979083776474],
      [0.8471502661705017, 0.639717161655426, 0.7417709231376648, 0.09149560332298279, 0.5411438345909119],
      [0.5077722072601318, 0.8713393807411194, 0.36126405000686646, 0.5981840491294861, 0.05925164371728897],
      [0.3876318037509918, 0.3230363428592682, 0.15019972622394562, 0.8163381218910217, 0.3794461786746979],
      [0.9787479043006897, 0.5899916887283325, 0.6050562262535095, 0.6379965543746948, 0.676450252532959],
      [0.15078802406787872, 0.440313458442688, 0.2395639568567276, 0.4024983048439026, 0.09670409560203552]],
    limit: 0.8, matches: [[0, 1], [1, 3], [2, 4], [3, 2], [5, 0]] },
  ];

  it.each(cases)("matches lapjv for a $limit cost limit", ({ cost, limit, matches }) => {
    expect(linearAssignment(cost, limit).matches).toEqual(matches);
  });

  it("leaves everything unmatched for empty inputs", () => {
    expect(linearAssignment([], 0.8, 3)).toEqual({ matches: [], unmatchedRows: [], unmatchedColumns: [0, 1, 2] });
    expect(linearAssignment([[], []], 0.8, 0).unmatchedRows).toEqual([0, 1]);
  });
});

describe("ByteTracker", () => {
  it("confirms first-frame tracks at once and keeps their IDs while objects move", () => {
    const tracker = new ByteTracker(config);
    expect(ids(tracker, [car(10), car(300)])).toEqual([1, 2]);
    expect(ids(tracker, [car(14), car(296)])).toEqual([1, 2]);
    expect(ids(tracker, [car(300 - 8), car(18)])).toEqual([2, 1]); // order of the input does not matter
  });

  it("reports a later new object without an ID until a second frame confirms it", () => {
    const tracker = new ByteTracker(config);
    ids(tracker, [car(10)]);
    expect(ids(tracker, [car(12), car(400)])).toEqual([1, null]);
    expect(ids(tracker, [car(14), car(402)])).toEqual([1, 2]);
  });

  it("keeps a track through a low-score frame (second association) but reports low boxes only when tracked", () => {
    const tracker = new ByteTracker(config);
    ids(tracker, [car(10)]);
    const lowFrame = tracker.update([car(12, 0.18), car(500, 0.18)]);
    expect(lowFrame.objects.map((o) => [o.box[0], o.trackId])).toEqual([[12, 1]]); // the stray low box is dropped
    expect(ids(tracker, [car(14)])).toEqual([1]);
  });

  it("re-finds a lost track within the buffer and retires it after", () => {
    const short = new ByteTracker({ ...config, trackBuffer: 3 });
    ids(short, [car(10)]);
    ids(short, []);
    ids(short, []);
    expect(ids(short, [car(14)])).toEqual([1]); // lost for 2 frames: same ID

    const retired = new ByteTracker({ ...config, trackBuffer: 2 });
    ids(retired, [car(10)]);
    for (let i = 0; i < 4; i++) ids(retired, []);
    expect(ids(retired, [car(10)])).toEqual([null]); // a new, unconfirmed track
    expect(ids(retired, [car(10)])).toEqual([2]);
  });

  it("drops an unconfirmed track that is not seen again", () => {
    const tracker = new ByteTracker(config);
    ids(tracker, [car(10)]);
    ids(tracker, [car(12), car(400)]); // 400: new, unconfirmed
    ids(tracker, [car(14)]); // 400 missing: removed
    expect(ids(tracker, [car(16), car(404)])).toEqual([1, null]);
    expect(tracker.size).toBeLessThanOrEqual(2);
  });

  it("ignores degenerate boxes and only starts tracks from boxes at the confidence threshold", () => {
    const tracker = new ByteTracker(config);
    const frame = tracker.update([{ classId: 2, confidence: 0.9, box: [10, 10, 10, 50] }, car(100, 0.2)]);
    // Like the Python ObjectTracker: a box at the threshold is still reported, but a zero-width box is
    // never tracked; a box below the threshold that continues no track is not reported.
    expect(frame.objects.map((o) => [o.confidence, o.trackId])).toEqual([[0.9, null]]);
    expect(frame.activeTracks).toBe(0);
  });

  it("rejects invalid configurations", () => {
    expect(() => new ByteTracker({ ...config, confidence: 2 })).toThrow();
    expect(() => new ByteTracker({ ...config, trackBuffer: 0 })).toThrow();
  });
});

describe("TrackerHost (Web Worker state)", () => {
  const frame = (sessionId: string, frameId: number, detections = [car(10 + frameId)], timestampMs = frameId * 200) =>
    ({ type: "TRACK_FRAME" as const, sessionId, frameId, timestampMs, width: 640, height: 480, detections });

  it("tracks per session, isolated from other sessions", () => {
    const host = new TrackerHost(() => 0);
    host.handle({ type: "INIT", sessionId: "a", config });
    host.handle({ type: "INIT", sessionId: "b", config });
    host.handle(frame("a", 1, [car(10), car(300)]));
    const [b] = host.handle(frame("b", 1, [car(300)]));
    expect(b.type === "TRACKED" && b.objects.map((o) => o.trackId)).toEqual([1]); // IDs start at 1 per session
  });

  it("skips stale and repeated frames instead of feeding them to ByteTrack", () => {
    const host = new TrackerHost(() => 0);
    host.handle({ type: "INIT", sessionId: "a", config });
    host.handle(frame("a", 5));
    expect(host.handle(frame("a", 5))[0]).toMatchObject({ type: "SKIPPED", reason: "STALE" });
    expect(host.handle(frame("a", 3))[0]).toMatchObject({ type: "SKIPPED", reason: "STALE" });
    expect(host.handle(frame("a", 9))[0]).toMatchObject({ type: "TRACKED", frameId: 9, restarted: false });
  });

  it("restarts tracking after a long pause or a reset, and forgets closed sessions", () => {
    const host = new TrackerHost(() => 0, 1_000);
    host.handle({ type: "INIT", sessionId: "a", config });
    expect(host.handle(frame("a", 1))[0]).toMatchObject({ restarted: true });
    expect(host.handle(frame("a", 2, undefined, 900))[0]).toMatchObject({ restarted: false });
    expect(host.handle(frame("a", 3, undefined, 5_000))[0]).toMatchObject({ restarted: true });
    host.handle({ type: "RESET", sessionId: "a" });
    expect(host.handle(frame("a", 1, undefined, 5_100))[0]).toMatchObject({ type: "TRACKED", restarted: true });
    expect(host.handle({ type: "CLOSE", sessionId: "a" })).toEqual([{ type: "CLOSED", sessionId: "a" }]);
    expect(host.handle(frame("a", 2))[0]).toMatchObject({ type: "SKIPPED", reason: "UNKNOWN_SESSION" });
  });

  it("bounds the number of sessions and rejects invalid configurations", () => {
    const host = new TrackerHost(() => 0);
    for (let i = 0; i < 6; i++) host.handle({ type: "INIT", sessionId: `s${i}`, config });
    expect(host.sessionCount).toBe(4);
    expect(host.handle({ type: "INIT", sessionId: "bad", config: { ...config, trackBuffer: 0 } })[0])
      .toMatchObject({ type: "ERROR" });
  });
});
