"""Tracking metadata stored in result.json (tracking mode only).

Track IDs come from ByteTrack and are scoped to one video job. ``unique_track_ids`` counts the
IDs that were assigned, which is not guaranteed to equal the number of physical objects: an
object can be split into several IDs (fragmentation after occlusion) or, more rarely, two
objects can swap IDs.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.base import EngineSchema

TRACKER_NAME = "bytetrack"
TRACK_COUNT_SEMANTICS = "TRACK_IDS_ASSIGNED_BY_BYTETRACK"


class TrackerParameters(EngineSchema):
    """The ByteTrack thresholds actually used, derived from the job's confidence."""

    inference_confidence: float = Field(ge=0, le=1)
    track_high_thresh: float = Field(ge=0, le=1)
    track_low_thresh: float = Field(ge=0, le=1)
    new_track_thresh: float = Field(ge=0, le=1)
    match_thresh: float = Field(ge=0, le=1)
    track_buffer: int = Field(ge=1)
    fuse_score: bool


class TrackSummary(EngineSchema):
    track_id: int = Field(ge=1)
    class_id: int = Field(ge=0)
    class_name: str
    first_frame: int = Field(ge=0)
    last_frame: int = Field(ge=0)
    first_timestamp_ms: int = Field(ge=0)
    last_timestamp_ms: int = Field(ge=0)
    frames_observed: int = Field(ge=1)
    average_confidence: float = Field(ge=0, le=1)
    max_confidence: float = Field(ge=0, le=1)
    # [x1, y1, x2, y2] in source-video pixels, like every other box in this project.
    last_box: tuple[float, float, float, float]


class TrackingStatistics(EngineSchema):
    tracker: Literal["bytetrack"] = TRACKER_NAME
    count_semantics: Literal["TRACK_IDS_ASSIGNED_BY_BYTETRACK"] = TRACK_COUNT_SEMANTICS
    parameters: TrackerParameters
    unique_track_ids: int = Field(ge=0)
    unique_track_ids_by_class: dict[str, Annotated[int, Field(ge=0)]]
    max_active_tracks: int = Field(ge=0)
    average_active_tracks: float = Field(ge=0)
    frames_with_tracks: int = Field(ge=0)
    # Reported boxes that carried a Track ID vs boxes at or above the confidence threshold
    # that had no confirmed track yet (a new object is confirmed on its second frame).
    tracked_detections: int = Field(ge=0)
    untracked_detections: int = Field(ge=0)
    tracks: list[TrackSummary]
    tracks_truncated: bool = False
