import { describe, expect, it } from "vitest";
import { model } from "../test/fixtures";
import { initialFormState, parseConfidence, toRequest, validateForm, type DetectionFormState } from "./detectionForm";

const URL = "https://www.youtube.com/watch?v=abcdefghijk";
const enabled = model({ enabled: true });
const valid = (overrides: Partial<DetectionFormState> = {}): DetectionFormState => ({
  ...initialFormState(),
  videoUrl: URL,
  ...overrides,
});

describe("detection form", () => {
  it("starts with the documented defaults", () => {
    expect(initialFormState()).toEqual({
      videoUrl: "",
      confidence: "0.25",
      imageSize: 640,
      classes: [1, 2, 3, 5, 7],
    });
  });

  it.each([
    ["0", 0],
    ["1", 1],
    ["0.25", 0.25],
    ["0.125", 0.125],
    [".5", 0.5],
    ["1.000", 1],
    [" 0.3 ", 0.3],
  ])("parses the confidence %s", (text, value) => {
    expect(parseConfidence(text)).toBe(value);
  });

  it.each(["", "-0.1", "1.01", "2", "0.1234", "abc", "1e-1", "0,5"])(
    "rejects the confidence %s",
    (text) => {
      expect(parseConfidence(text)).toBeNull();
    },
  );

  it("accepts a valid form for an enabled detection model", () => {
    expect(validateForm(valid(), enabled)).toEqual({});
  });

  it("blocks missing, disabled, and non-detection models", () => {
    expect(validateForm(valid(), undefined).modelKey).toBe("Select a registered model.");
    expect(validateForm(valid(), model()).modelKey).toMatch(/yolo11n is disabled/);
    expect(validateForm(valid(), model({ enabled: true, taskType: "SEGMENT" })).modelKey).toMatch(
      /not an object detection model/,
    );
  });

  it("reports each invalid field", () => {
    const errors = validateForm(
      { videoUrl: "https://example.com", confidence: "1.5", imageSize: 500, classes: [] },
      enabled,
    );
    expect(Object.keys(errors).sort()).toEqual(["classes", "confidence", "imageSize", "videoUrl"]);
    expect(validateForm(valid({ classes: [1, 1] }), enabled).classes).toMatch(/invalid entries/);
    expect(validateForm(valid({ classes: [80] }), enabled).classes).toMatch(/invalid entries/);
  });

  it("builds exactly the public request body", () => {
    const body = toRequest(
      valid({ videoUrl: `  ${URL} `, confidence: "0.4", imageSize: 960, classes: [7, 0, 2, 0] }),
      enabled,
    );
    expect(body).toEqual({
      videoUrl: URL,
      modelKey: "yolo11n",
      confidence: 0.4,
      imageSize: 960,
      classes: [0, 2, 7],
    });
    expect(Object.keys(body).sort()).toEqual(["classes", "confidence", "imageSize", "modelKey", "videoUrl"]);
  });
});
