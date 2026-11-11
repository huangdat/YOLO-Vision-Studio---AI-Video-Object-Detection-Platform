/**
 * Browser camera access for Live Detection. Video only (never audio), requested only after a
 * user action. Cameras work on secure contexts: https:// or http://localhost.
 */
export interface CameraDevice {
  deviceId: string;
  label: string;
}

export type CameraProblemCode = "UNSUPPORTED" | "INSECURE" | "DENIED" | "NOT_FOUND" | "IN_USE" | "UNKNOWN";

export interface CameraProblem {
  code: CameraProblemCode;
  message: string;
}

/** Why the camera cannot be used at all in this browser context, or null when it can. */
export function cameraSupportProblem(win: Window = window): CameraProblem | null {
  if (!win.isSecureContext) {
    return {
      code: "INSECURE",
      message:
        "Camera access needs a secure connection. Open the app on http://localhost, or serve it over HTTPS.",
    };
  }
  if (!win.navigator.mediaDevices?.getUserMedia) {
    return { code: "UNSUPPORTED", message: "This browser does not support camera access." };
  }
  return null;
}

export function describeCameraError(error: unknown): CameraProblem {
  const name = error instanceof DOMException || (error instanceof Error && error.name) ? (error as Error).name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return {
        code: "DENIED",
        message: "Camera permission was denied. Allow camera access in the browser's site settings and try again.",
      };
    case "NotFoundError":
    case "OverconstrainedError":
      return { code: "NOT_FOUND", message: "No camera was found. Connect a webcam and try again." };
    case "NotReadableError":
    case "AbortError":
      return {
        code: "IN_USE",
        message: "The camera could not be started. It may be in use by another application.",
      };
    default:
      return { code: "UNKNOWN", message: "The camera could not be started." };
  }
}

export async function listCameras(media: MediaDevices = navigator.mediaDevices): Promise<CameraDevice[]> {
  const devices = await media.enumerateDevices();
  return devices
    .filter((device) => device.kind === "videoinput")
    .map((device, index) => ({ deviceId: device.deviceId, label: device.label || `Camera ${index + 1}` }));
}

/** Opens one camera at about 640×480; the caller owns (and must stop) the returned stream. */
export function openCamera(deviceId: string | undefined, media: MediaDevices = navigator.mediaDevices) {
  return media.getUserMedia({
    audio: false,
    video: {
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      width: { ideal: 640 },
      height: { ideal: 480 },
      frameRate: { ideal: 15, max: 30 },
    },
  });
}

export function stopStream(stream: MediaStream | null | undefined): void {
  stream?.getTracks().forEach((track) => track.stop());
}
