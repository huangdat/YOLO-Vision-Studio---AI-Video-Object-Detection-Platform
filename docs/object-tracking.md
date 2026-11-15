# Object Tracking (ByteTrack)

Object tracking is an opt-in processing mode for both YouTube video jobs and Live Detection. Detection
finds objects in each frame independently. Tracking also links those detections across consecutive frames,
so the same object keeps a **Track ID** (`car #7`) for as long as ByteTrack can follow it.

| Mode | What runs | Output |
| --- | --- | --- |
| `DETECTION_ONLY` (default) | YOLO per frame | Boxes with class and confidence |
| `DETECTION_TRACKING` | YOLO per frame + ByteTrack | The same boxes, plus a Track ID for each confirmed track |

Jobs created before tracking existed, and requests that omit the mode, are Detection Only. Existing result
files and API responses keep working unchanged.

## Why ByteTrack

- **Online.** It associates each frame using only earlier frames. Live streams can use it, and a recorded video
  is processed in a single forward pass. This implementation is online tracking, even for prerecorded
  YouTube videos. It never revisits past frames (no offline or global association).
- **Lightweight.** It uses a Kalman filter for motion and box overlap (IoU) for matching, with no appearance
  (Re-ID) model, so it adds no model downloads and runs on CPU.
- **Recovers weak detections.** A second association stage matches low-confidence boxes to existing tracks,
  which keeps IDs through partial occlusion.
- **Ships with the pinned Ultralytics version** (`ultralytics/trackers/byte_tracker.py`, `bytetrack.yaml`).
  The only extra dependency is `lap` (BSD-2-Clause), which ByteTrack uses for its linear assignment. It is pinned
  in `ai-worker/requirements-ai.txt` so Ultralytics never tries to install it at runtime.

DeepSORT, BoT-SORT, OC-SORT, Re-ID models, and offline refinement are deliberately not used.

## How Track IDs work

- One `ObjectTracker` (`ai-worker/app/services/object_tracking.py`) wraps one Ultralytics `BYTETracker` and
  belongs to exactly one video job or one live session. IDs start at 1 for every job and session.
- The YOLO weights stay shared and cached. Detection still runs under the model's lock. Only the small tracker
  state is per stream. Ultralytics' `model.track(persist=True)` is not used, because it keeps tracker state and
  callbacks on the shared model object, which could leak IDs between jobs or sessions.
- A new object is confirmed on its second consecutive frame. Until then its box is reported with `trackId: null`.
  The UI never invents an ID.
- A lost track is kept for `track_buffer` processed frames: 30 for videos (`AI_TRACKING_TRACK_BUFFER`) and 10 for
  live sessions (`LIVE_TRACKING_TRACK_BUFFER`). If the object is matched again in that window, it keeps its ID.
- Boxes keep the project's coordinate convention, `[x1, y1, x2, y2]` in source-frame pixels. The detector's own box
  is reported, not the Kalman prediction.

### Confidence

ByteTrack needs low-score boxes for its second association stage. In tracking mode YOLO therefore runs at
`min(confidence, 0.1)` internally. The user's confidence is still the threshold for:

- detection-event counts (`detectionSummary`, the same set Detection Only reports, because greedy NMS keeps the
  same high-score boxes);
- first-stage matching and starting new tracks (`track_high_thresh = new_track_thresh = confidence`).

A box below the threshold is shown only when it continues an existing track, and it is shown with its real score.
The thresholds actually used are stored in `result.json` under `tracking.parameters`.

## YouTube video jobs

1. On **New Detection**, switch on **Object tracking** (step 3).
2. `POST /api/v1/detections` sends `"processingMode": "DETECTION_TRACKING"`. Spring Boot validates and persists it
   (`detection_jobs.processing_mode`, Flyway V8) and adds it to the outbox command. Detection-only commands omit
   the field, so they are byte-for-byte unchanged.
3. The worker processes **every decoded frame in order**. There is no frame sampling, so continuity is limited only
   by the detector and the scene. A new tracker is created for the job and closed when the job completes, fails,
   or is interrupted.
4. The annotated MP4 shows `car #7 0.94` labels, each track in its own colour, with a short faded trail (the last
   20 centres, `AI_TRACKING_TRAJECTORY_LENGTH`). Detections without a confirmed track are drawn in grey without
   an ID.
5. `result.json` (download from the job page) adds `processingMode` and a `tracking` section with the totals, the
   parameters, and one summary per track (`trackId`, class, first and last frame and timestamp, frames observed,
   average and maximum confidence, last box). At most 5,000 track summaries are stored
   (`AI_TRACKING_MAX_REPORTED_TRACKS`); beyond that, `tracksTruncated` is `true` and IDs are still counted.
6. The completion event carries compact totals, which are stored in `detection_results.tracking_summary`.
   `GET /api/v1/detections/{jobId}/result` returns them as `tracking`, and the job page shows them.

## Live Detection

1. On **Live Detection**, switch on **Object tracking** before **Start**. The choice is locked while the session
   runs.
2. The `start` message carries `"tracking": true`. `ready` answers `tracking: true, tracker: "bytetrack"`.
3. Spring Boot forwards each frame with its own server-generated `sessionId`. The live worker keeps one tracker
   per session ID, in memory only. Nothing is stored.
4. `detections` messages add `trackId` to confirmed detections, plus `tracking: true` and `activeTracks`. The
   overlay labels boxes `Person #3 · 91%` and draws short trails from the IDs it received.
5. The existing backpressure is unchanged: one frame in flight, at most 5 FPS, and no queue. Frames the gateway
   drops never reach the tracker. The worker rejects a frame older than one it has already tracked
   (`FRAME_OUT_OF_ORDER`).
6. **Cleanup.** Stop, disconnect, idle timeout, maximum duration, errors, and shutdown all end the session, and the
   gateway calls `DELETE /internal/live/sessions/{sessionId}`. The worker also expires idle tracking sessions
   (`LIVE_TRACKING_SESSION_TTL_SECONDS`, 30 s) and holds at most `LIVE_MAX_TRACKING_SESSIONS` (4). An ended session
   is never revived. Every new session, including after a reconnect or a camera change, starts at ID 1.

## Counts: what each number means

| Number | Meaning |
| --- | --- |
| Detection events (`totalDetections`) | Boxes at or above the confidence threshold, summed over all frames. One car visible in 60 frames counts 60 times. Same meaning in both modes |
| Active tracks | Confirmed tracks in one frame (live: the last frame; videos: `maxActiveTracks` is the peak) |
| Unique track IDs (`uniqueTrackIds`) | Distinct IDs ByteTrack assigned within the job |

Unique track IDs approximate the number of distinct objects, but they are not a guaranteed object count. An object
that is occluded for longer than the track buffer, leaves and re-enters, or is missed for several frames gets a new
ID (fragmentation). Objects crossing closely can swap IDs. IDs are never global or permanent: they are scoped to one
job or one live session.

## Limitations

- **Fragmentation and ID switches** under long occlusions, crowds, fast motion, or a moving camera (ByteTrack has no
  camera-motion compensation).
- **Sparse live frames.** At a few frames per second on CPU, objects move further between frames, so IoU matching is
  less reliable than in videos processed at full frame rate.
- **Detector-bound.** Missed detections cannot be tracked. Tracking does not improve detection accuracy.
- **IDs are not consecutive.** ByteTrack also numbers tentative tracks that are never confirmed, so the highest ID
  can be well above the number of unique track IDs.

## Measured results (CPU, Docker Desktop on Windows)

These are single runs on one machine, not benchmarks. They show the behaviour, not guaranteed numbers.

| Run | Result |
| --- | --- |
| YouTube job through the full stack (`yolo11n`, 640 px, 1280 × 720, 25 FPS, 1,192 frames, classes person, bicycle, car, motorcycle, bus, truck) | Completed in 138 s. 11,844 detection events; 137 unique track IDs; at most 21 active tracks. 46 tracks lasted at least 100 frames (one bus kept ID 88 for 854 frames, about 34 s); 32 tracks lasted at most 5 frames (fragmentation of small or distant objects). The MP4 shows `car #190 0.68`-style labels and trails. |
| Live Detection through the WebSocket gateway (20 frames of a 640 × 480 sample used as the camera, `yolo11n`, 416 px) | Four objects kept IDs 1–4 in all 20 frames; a new object arrived with `trackId: null` before it was confirmed. A second session started again at ID 1 with independent state. The worker released each session's tracker when its WebSocket closed. Median round trip about 105 ms (tracking) and 104 ms (detection only). |
| 60-frame sample in process | The bus and three people kept the same IDs in all 60 frames. Detection events were identical in both modes (300 and 300). Run-to-run timing varied more (5.7–11.8 s) than the difference between modes, so no tracking overhead figure is claimed. |

No physical webcam was used: the live run fed video frames through the same WebSocket protocol as the browser.

## Licensing

Ultralytics (including its ByteTrack implementation) is licensed under AGPL-3.0, like the rest of the inference stack
this project already uses. `lap` is BSD-2-Clause. Check these terms before distributing or offering the software as a
network service.
