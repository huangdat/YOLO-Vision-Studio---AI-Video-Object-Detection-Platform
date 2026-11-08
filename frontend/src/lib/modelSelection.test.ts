import { describe, expect, it } from "vitest";
import { model } from "../test/fixtures";
import {
  availableVersions,
  choiceForVersion,
  defaultChoice,
  modelsForVersion,
  reconcileChoice,
  resolveModel,
} from "./modelSelection";

const order = ["YOLOv8", "YOLO11", "YOLO12", "YOLO26"];
const catalog = [
  model({ modelKey: "yolo26s", version: "YOLO26", modelSize: "s" }),
  model({ modelKey: "yolov8n", version: "YOLOv8", modelSize: "n" }),
  model({ modelKey: "yolo11m", version: "YOLO11", modelSize: "m" }),
  model({ modelKey: "yolo11n", version: "YOLO11", modelSize: "n", enabled: true }),
  model({ modelKey: "yolo26n", version: "YOLO26", modelSize: "n" }),
];

describe("model selection", () => {
  it("lists only versions with registered models, in release order", () => {
    expect(availableVersions(catalog, order)).toEqual(["YOLOv8", "YOLO11", "YOLO26"]);
    expect(availableVersions([model({ version: "YOLOX" })], order)).toEqual(["YOLOX"]);
  });

  it("sorts sizes smallest first", () => {
    expect(modelsForVersion(catalog, "YOLO11").map((item) => item.modelKey)).toEqual(["yolo11n", "yolo11m"]);
  });

  it("resolves only pairs that exist in the catalog", () => {
    expect(resolveModel(catalog, { version: "YOLO11", size: "m" })?.modelKey).toBe("yolo11m");
    expect(resolveModel(catalog, { version: "YOLO12", size: "n" })).toBeUndefined();
    expect(resolveModel(catalog, { version: "YOLOv8", size: "x" })).toBeUndefined();
    expect(resolveModel(catalog, null)).toBeUndefined();
  });

  it("defaults to the first enabled model, else the first registered model", () => {
    expect(defaultChoice(catalog, order)).toEqual({ version: "YOLO11", size: "n" });
    const none = catalog.map((item) => ({ ...item, enabled: false }));
    expect(defaultChoice(none, order)).toEqual({ version: "YOLOv8", size: "n" });
    expect(defaultChoice([], order)).toBeNull();
  });

  it("keeps the size across versions when it exists, else prefers an enabled size", () => {
    expect(choiceForVersion(catalog, "YOLO26", "s")).toEqual({ version: "YOLO26", size: "s" });
    expect(choiceForVersion(catalog, "YOLO11", "s")).toEqual({ version: "YOLO11", size: "n" });
    expect(choiceForVersion(catalog, "YOLO26", "x")).toEqual({ version: "YOLO26", size: "n" });
    expect(choiceForVersion(catalog, "YOLO12", "n")).toBeNull();
  });

  it("keeps a still-registered choice after reload and replaces a stale one", () => {
    expect(reconcileChoice(catalog, order, { version: "YOLO26", size: "s" })).toEqual({
      version: "YOLO26",
      size: "s",
    });
    const reloaded = catalog.filter((item) => item.modelKey !== "yolo26s");
    expect(reconcileChoice(reloaded, order, { version: "YOLO26", size: "s" })).toEqual({
      version: "YOLO11",
      size: "n",
    });
  });
});
