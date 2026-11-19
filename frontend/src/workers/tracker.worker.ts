/// <reference lib="webworker" />
/**
 * Dedicated Web Worker running ByteTrack for Live Detection, off the UI thread. All logic lives in
 * TrackerHost (unit tested); this file only connects it to postMessage.
 */
import { TrackerHost } from "../lib/tracking/trackerHost";
import type { TrackerRequest } from "../lib/tracking/trackerProtocol";

const host = new TrackerHost();
const scope = self as unknown as DedicatedWorkerGlobalScope;

scope.onmessage = (event: MessageEvent<TrackerRequest>) => {
  let responses;
  try {
    responses = host.handle(event.data);
  } catch (error) {
    responses = [{ type: "ERROR" as const, sessionId: event.data?.sessionId ?? "", message: (error as Error).message }];
  }
  for (const response of responses) scope.postMessage(response);
};
