import type { CreateDetectionRequest } from "../types/detections";
import type { ModelConfig } from "../types/models";
import { isKnownClass, VEHICLE_CLASS_IDS } from "./cocoClasses";
import { checkYouTubeUrl } from "./youtube";

/** Inference sizes offered in the workspace; all are backend-valid multiples of 32. */
export const IMAGE_SIZES = [320, 640, 960, 1280] as const;
export const DEFAULT_IMAGE_SIZE = 640;
export const DEFAULT_CONFIDENCE = 0.25;
/** Backend limit (DetectionJobSubmissionRequest: 1-100 classes). */
export const MAX_CLASSES = 100;

export interface DetectionFormState {
  videoUrl: string;
  /** Kept as text so a partially typed value is not overwritten while editing. */
  confidence: string;
  imageSize: number;
  classes: number[];
}

export type FormField = "videoUrl" | "modelKey" | "confidence" | "imageSize" | "classes";
export type FormErrors = Partial<Record<FormField, string>>;

export function initialFormState(): DetectionFormState {
  return {
    videoUrl: "",
    confidence: DEFAULT_CONFIDENCE.toFixed(2),
    imageSize: DEFAULT_IMAGE_SIZE,
    classes: [...VEHICLE_CLASS_IDS],
  };
}

/** A confidence between 0 and 1 with at most three decimals (backend @Digits rule). */
export function parseConfidence(text: string): number | null {
  const value = text.trim();
  if (!/^(0(\.\d{1,3})?|1(\.0{1,3})?|\.\d{1,3})$/.test(value)) return null;
  const number = Number(value);
  return number >= 0 && number <= 1 ? number : null;
}

export function validateForm(form: DetectionFormState, model: ModelConfig | undefined): FormErrors {
  const errors: FormErrors = {};
  const url = checkYouTubeUrl(form.videoUrl);
  if (!url.valid) errors.videoUrl = url.message;
  if (!model) {
    errors.modelKey = "Select a registered model.";
  } else if (!model.enabled) {
    errors.modelKey = `${model.modelKey} is disabled. An administrator must enable it before jobs can use it.`;
  } else if (model.taskType !== "DETECT") {
    errors.modelKey = `${model.modelKey} is not an object detection model.`;
  }
  if (parseConfidence(form.confidence) === null) {
    errors.confidence = "Enter a value from 0 to 1 with at most three decimals.";
  }
  if (!(IMAGE_SIZES as readonly number[]).includes(form.imageSize)) {
    errors.imageSize = "Choose one of the supported image sizes.";
  }
  const unique = new Set(form.classes);
  if (form.classes.length === 0) {
    errors.classes = "Select at least one object class.";
  } else if (unique.size !== form.classes.length || form.classes.some((id) => !isKnownClass(id))) {
    errors.classes = "The class selection contains invalid entries.";
  } else if (form.classes.length > MAX_CLASSES) {
    errors.classes = `Select at most ${MAX_CLASSES} classes.`;
  }
  return errors;
}

/** The exact public request body: no other fields are sent. */
export function toRequest(form: DetectionFormState, model: ModelConfig): CreateDetectionRequest {
  return {
    videoUrl: form.videoUrl.trim(),
    modelKey: model.modelKey,
    confidence: parseConfidence(form.confidence) ?? DEFAULT_CONFIDENCE,
    imageSize: form.imageSize,
    classes: [...new Set(form.classes)].sort((a, b) => a - b),
  };
}
