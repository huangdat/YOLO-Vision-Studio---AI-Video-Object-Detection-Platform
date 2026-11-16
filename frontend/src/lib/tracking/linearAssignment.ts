/**
 * Minimum-cost assignment with a cost limit, matching `lap.lapjv(cost, extend_cost=True, cost_limit=t)`
 * as used by Ultralytics ByteTrack: the n x m cost matrix is extended to (n+m) x (n+m) with t/2 for
 * "leave unmatched" and 0 between the dummies, and solved optimally. A pair is therefore matched only
 * if that lowers the total cost, i.e. its cost is below t. Solved with the Hungarian algorithm
 * (O(N^3), N = n + m), which finds the same optimum as Jonker-Volgenant; only exact ties can differ.
 */

export interface Assignment {
  matches: [number, number][];
  unmatchedRows: number[];
  unmatchedColumns: number[];
}

/** Hungarian algorithm for a square cost matrix (rows assigned to columns, minimum total). */
function hungarian(cost: number[][]): number[] {
  const n = cost.length;
  const u = new Float64Array(n + 1);
  const v = new Float64Array(n + 1);
  const p = new Int32Array(n + 1); // p[j]: row assigned to column j (1-based), 0 = none
  const way = new Int32Array(n + 1);
  for (let i = 1; i <= n; i++) {
    p[0] = i;
    let j0 = 0;
    const minv = new Float64Array(n + 1).fill(Infinity);
    const used = new Uint8Array(n + 1);
    do {
      used[j0] = 1;
      const i0 = p[j0];
      let delta = Infinity;
      let j1 = 0;
      for (let j = 1; j <= n; j++) {
        if (used[j]) continue;
        const current = cost[i0 - 1][j - 1] - u[i0] - v[j];
        if (current < minv[j]) {
          minv[j] = current;
          way[j] = j0;
        }
        if (minv[j] < delta) {
          delta = minv[j];
          j1 = j;
        }
      }
      for (let j = 0; j <= n; j++) {
        if (used[j]) {
          u[p[j]] += delta;
          v[j] -= delta;
        } else {
          minv[j] -= delta;
        }
      }
      j0 = j1;
    } while (p[j0] !== 0);
    do {
      const j1 = way[j0];
      p[j0] = p[j1];
      j0 = j1;
    } while (j0);
  }
  const rowToColumn = new Array<number>(n).fill(-1);
  for (let j = 1; j <= n; j++) if (p[j] > 0) rowToColumn[p[j] - 1] = j - 1;
  return rowToColumn;
}

export function linearAssignment(cost: number[][], costLimit: number, columns?: number): Assignment {
  const rows = cost.length;
  const cols = columns ?? (rows ? cost[0].length : 0);
  if (rows === 0 || cols === 0) {
    return {
      matches: [],
      unmatchedRows: Array.from({ length: rows }, (_, i) => i),
      unmatchedColumns: Array.from({ length: cols }, (_, j) => j),
    };
  }
  const size = rows + cols;
  const extended = Array.from({ length: size }, (_, i) =>
    Array.from({ length: size }, (_, j) => {
      if (i < rows && j < cols) return cost[i][j];
      if (i >= rows && j >= cols) return 0;
      return costLimit / 2;
    }),
  );
  const rowToColumn = hungarian(extended);
  const matches: [number, number][] = [];
  const matchedColumns = new Set<number>();
  const unmatchedRows: number[] = [];
  for (let i = 0; i < rows; i++) {
    const j = rowToColumn[i];
    if (j >= 0 && j < cols) {
      matches.push([i, j]);
      matchedColumns.add(j);
    } else {
      unmatchedRows.push(i);
    }
  }
  const unmatchedColumns = Array.from({ length: cols }, (_, j) => j).filter((j) => !matchedColumns.has(j));
  return { matches, unmatchedRows, unmatchedColumns };
}
