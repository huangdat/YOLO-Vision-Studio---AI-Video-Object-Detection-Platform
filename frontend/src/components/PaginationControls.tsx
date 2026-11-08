import { Icon } from "./Icon";

/** Server-side pagination; pages are zero-based in the API and one-based for people. */
export function PaginationControls({
  page,
  totalPages,
  totalElements,
  pageSize,
  disabled,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  totalElements: number;
  pageSize: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
}) {
  const first = totalElements === 0 ? 0 : page * pageSize + 1;
  const last = Math.min(totalElements, (page + 1) * pageSize);
  return (
    <nav className="pagination" aria-label="Pagination">
      <p className="pagination-summary">
        {totalElements === 0
          ? "No records"
          : `Showing ${first}–${last} of ${totalElements.toLocaleString()}`}
      </p>
      <div className="pagination-buttons">
        <button
          type="button"
          className="button-secondary"
          onClick={() => onPageChange(page - 1)}
          disabled={disabled || page <= 0}
        >
          <Icon name="chevronLeft" size={14} />
          Previous
        </button>
        <span className="pagination-page" aria-current="page">
          Page {totalPages === 0 ? 0 : page + 1} of {totalPages}
        </span>
        <button
          type="button"
          className="button-secondary"
          onClick={() => onPageChange(page + 1)}
          disabled={disabled || page + 1 >= totalPages}
        >
          Next
          <Icon name="chevronRight" size={14} />
        </button>
      </div>
    </nav>
  );
}
