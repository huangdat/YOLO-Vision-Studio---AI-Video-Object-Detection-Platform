import { describe, expect, it } from "vitest";
import { ALL_CLASS_IDS, COCO_CLASSES, className, isKnownClass, VEHICLE_CLASS_IDS } from "./cocoClasses";

describe("COCO classes", () => {
  it("contains 80 unique classes with IDs 0-79 matching their index", () => {
    expect(COCO_CLASSES).toHaveLength(80);
    COCO_CLASSES.forEach((item, index) => expect(item.id).toBe(index));
    expect(new Set(COCO_CLASSES.map((item) => item.name)).size).toBe(80);
    expect(ALL_CLASS_IDS).toEqual(Array.from({ length: 80 }, (_, id) => id));
  });

  it("maps the vehicle preset to the expected COCO names", () => {
    expect(VEHICLE_CLASS_IDS).toEqual([1, 2, 3, 5, 7]);
    expect(VEHICLE_CLASS_IDS.map(className)).toEqual(["bicycle", "car", "motorcycle", "bus", "truck"]);
    expect(className(0)).toBe("person");
    expect(className(79)).toBe("toothbrush");
  });

  it("recognises only integer IDs in range", () => {
    expect(isKnownClass(0)).toBe(true);
    expect(isKnownClass(79)).toBe(true);
    expect(isKnownClass(80)).toBe(false);
    expect(isKnownClass(-1)).toBe(false);
    expect(isKnownClass(1.5)).toBe(false);
  });
});
