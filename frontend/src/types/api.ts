/** RFC 9457 problem details returned by every backend error (Phase 06 contract). */
export interface ApiProblem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  /** Stable application code such as JOB_NOT_FOUND or INVALID_DETECTION_REQUEST. */
  code?: string;
  timestamp?: string;
  /** Field name -> message, present for validation failures. */
  errors?: Record<string, string>;
  /** Present on RESULT_NOT_READY. */
  jobStatus?: string;
}

/** PageResponse<T> from the backend (not Spring Data's Page JSON). */
export interface PageResponse<T> {
  content: T[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
}
