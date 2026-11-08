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


class InferenceError(DetectionEngineError):
    """Inference did not finish successfully."""


class VideoProcessingError(DetectionEngineError):
    """A video could not be read or its annotated frames could not be written."""


class VideoEncodingError(DetectionEngineError):
    """Encoding or verification of the final MP4 failed."""
