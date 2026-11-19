"""Errors that callers can handle without depending on FastAPI or a queue."""


class DetectionEngineError(Exception):
    """Base error for an unsuccessful detection execution."""


class InvalidVideoSourceError(DetectionEngineError):
    """The source is unsupported, malformed, or outside the allowed input root."""


class VideoDownloadError(DetectionEngineError):
    """An authorized video could not be downloaded."""


class VideoLimitExceededError(DetectionEngineError):
    """A source exceeds a configured size, duration, or decoded-frame limit."""


class ModelLoadingError(DetectionEngineError):
    """The requested model or device is unavailable."""


class Int8ModelUnavailableError(ModelLoadingError):
    """INT8 was requested explicitly, but no usable INT8 model exists on this worker (no artifact,
    an invalid or stale one, no OpenVINO runtime, or a non-CPU device). Not retryable."""


class InferenceError(DetectionEngineError):
    """Inference did not finish successfully."""


class VideoProcessingError(DetectionEngineError):
    """A video could not be read or its annotated frames could not be written."""


class VideoProbeError(VideoProcessingError):
    """FFprobe could not identify the input as a valid media file."""


class VideoStreamMissingError(VideoProcessingError):
    """The input contains no video stream (for example, an audio-only file)."""


class UnsupportedVideoCodecError(VideoProcessingError):
    """The input stream cannot be decoded into frames, even after normalization."""


class VideoNormalizationError(VideoProcessingError):
    """FFmpeg could not convert the input into an OpenCV-compatible video."""


class VideoEncodingError(DetectionEngineError):
    """Encoding or verification of the final MP4 failed."""


class ArtifactStorageError(DetectionEngineError):
    """Completed artifacts could not be stored durably or read back."""


class QuantizationError(DetectionEngineError):
    """An INT8 model could not be exported, calibrated, or validated."""
