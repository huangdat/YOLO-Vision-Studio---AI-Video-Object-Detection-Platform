/**
 * TypeScript ByteTrack vs Python ByteTrack on identical, real YOLO detection sequences.
 * Fixtures come from `python -m benchmarks.tracker_parity` (ai-worker): real detections plus the Track IDs
 * the Python ObjectTracker assigned. `__fixtures__/local/` holds fixtures derived from licensed datasets
 * (MOT17), which are not committed; they are included when present.
 */
import { describe, expect, it } from "vitest";
import { ByteTracker, type TrackerConfig, type TrackerDetection } from "./byteTracker";

interface Fixture {
  name: string;
  config: TrackerConfig;
  frames: { detections: number[][]; expected: { objects: [number, number | null][]; activeTracks: number } }[];
  python: { frames: number; boxes: number; trackingMsMean: number; trackingMsP95: number };
}

const fixtures = Object.values(
  import.meta.glob<Fixture>("./__fixtures__/**/parity-*.json", { eager: true, import: "default" }),
);

function detections(rows: number[][]): TrackerDetection[] {
  return rows.map(([classId, confidence, x1, y1, x2, y2]) => ({ classId, confidence, box: [x1, y1, x2, y2] }));
}

describe("ByteTrack parity with the Python workers", () => {
  it("has committed fixtures", () => {
    expect(fixtures.length).toBeGreaterThanOrEqual(2);
  });

  it.each(fixtures.map((fixture) => [fixture.name, fixture] as const))(
    "assigns exactly the Python Track IDs on %s",
    (_name, fixture) => {
      const tracker = new ByteTracker(fixture.config);
      const timings: number[] = [];
      let mismatchedFrames = 0;
      fixture.frames.forEach((frame, index) => {
        const started = performance.now();
        const result = tracker.update(detections(frame.detections));
        timings.push(performance.now() - started);
        const rows = frame.detections;
        const actual = result.objects.map((object) => {
          const inputIndex = rows.findIndex((row) => row[1] === object.confidence && row[2] === object.box[0]
            && row[3] === object.box[1] && row[4] === object.box[2] && row[5] === object.box[3]);
          return [inputIndex, object.trackId];
        });
        if (JSON.stringify(actual) !== JSON.stringify(frame.expected.objects)
            || result.activeTracks !== frame.expected.activeTracks) {
          mismatchedFrames += 1;
          if (mismatchedFrames === 1) {
            expect({ frame: index, objects: actual, activeTracks: result.activeTracks })
              .toEqual({ frame: index, ...frame.expected });
          }
        }
      });
      const sorted = [...timings].sort((a, b) => a - b);
      const mean = timings.reduce((sum, value) => sum + value, 0) / timings.length;
      console.info(JSON.stringify({
        fixture: fixture.name, frames: fixture.frames.length, boxes: fixture.python.boxes, mismatchedFrames,
        typescriptMsMean: Number(mean.toFixed(4)), typescriptMsP95: Number(sorted[Math.floor(0.95 * (sorted.length - 1))].toFixed(4)),
        pythonMsMean: fixture.python.trackingMsMean, pythonMsP95: fixture.python.trackingMsP95,
      }));
      expect(mismatchedFrames).toBe(0);
    },
  );
});
