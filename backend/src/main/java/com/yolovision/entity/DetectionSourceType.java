package com.yolovision.entity;

/** Where the worker obtains the input video; persisted by name. */
public enum DetectionSourceType {
    /** A single public YouTube video, revalidated by the worker before download. */
    YOUTUBE_URL,
    /** A relative path inside the worker's AI_LOCAL_INPUT_DIR (development and testing). */
    LOCAL_FILE
}
