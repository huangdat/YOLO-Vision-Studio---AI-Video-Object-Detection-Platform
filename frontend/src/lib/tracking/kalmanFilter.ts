/**
 * Constant-velocity Kalman filter in (x, y, a, h) image space: center x/y, aspect ratio a = w/h,
 * height h, and their velocities. A port of Ultralytics' KalmanFilterXYAH (the filter ByteTrack uses),
 * with the same noise weights, in float64 like NumPy.
 */

export type Vector = number[];
export type Matrix = number[][];

const NDIM = 4;
const STD_WEIGHT_POSITION = 1 / 20;
const STD_WEIGHT_VELOCITY = 1 / 160;

function zeros(rows: number, cols: number): Matrix {
  return Array.from({ length: rows }, () => new Array<number>(cols).fill(0));
}

function diagonal(values: number[]): Matrix {
  const result = zeros(values.length, values.length);
  values.forEach((value, index) => (result[index][index] = value));
  return result;
}

function multiply(a: Matrix, b: Matrix): Matrix {
  const result = zeros(a.length, b[0].length);
  for (let i = 0; i < a.length; i++) {
    for (let k = 0; k < b.length; k++) {
      const value = a[i][k];
      if (value === 0) continue;
      for (let j = 0; j < b[0].length; j++) result[i][j] += value * b[k][j];
    }
  }
  return result;
}

function transpose(a: Matrix): Matrix {
  return a[0].map((_, column) => a.map((row) => row[column]));
}

/** Solves A X = B for X (A square), Gaussian elimination with partial pivoting like LAPACK gesv. */
export function solve(a: Matrix, b: Matrix): Matrix {
  const n = a.length;
  const m = b[0].length;
  const lu = a.map((row) => [...row]);
  const x = b.map((row) => [...row]);
  for (let column = 0; column < n; column++) {
    let pivot = column;
    for (let row = column + 1; row < n; row++) {
      if (Math.abs(lu[row][column]) > Math.abs(lu[pivot][column])) pivot = row;
    }
    if (lu[pivot][column] === 0) throw new Error("Singular matrix in Kalman update");
    [lu[column], lu[pivot]] = [lu[pivot], lu[column]];
    [x[column], x[pivot]] = [x[pivot], x[column]];
    for (let row = column + 1; row < n; row++) {
      const factor = lu[row][column] / lu[column][column];
      if (factor === 0) continue;
      for (let k = column; k < n; k++) lu[row][k] -= factor * lu[column][k];
      for (let k = 0; k < m; k++) x[row][k] -= factor * x[column][k];
    }
  }
  for (let row = n - 1; row >= 0; row--) {
    for (let k = 0; k < m; k++) {
      let value = x[row][k];
      for (let j = row + 1; j < n; j++) value -= lu[row][j] * x[j][k];
      x[row][k] = value / lu[row][row];
    }
  }
  return x;
}

const MOTION: Matrix = (() => {
  const result = diagonal(new Array(2 * NDIM).fill(1));
  for (let i = 0; i < NDIM; i++) result[i][NDIM + i] = 1; // dt = 1 frame
  return result;
})();
const MOTION_T = transpose(MOTION);

export interface KalmanState {
  mean: Vector;
  covariance: Matrix;
}

export const kalmanFilter = {
  /** New track from an unassociated measurement (x, y, a, h). */
  initiate(measurement: Vector): KalmanState {
    const h = measurement[3];
    const std = [
      2 * STD_WEIGHT_POSITION * h, 2 * STD_WEIGHT_POSITION * h, 1e-2, 2 * STD_WEIGHT_POSITION * h,
      10 * STD_WEIGHT_VELOCITY * h, 10 * STD_WEIGHT_VELOCITY * h, 1e-5, 10 * STD_WEIGHT_VELOCITY * h,
    ];
    return { mean: [...measurement, 0, 0, 0, 0], covariance: diagonal(std.map((value) => value * value)) };
  },

  /** One-frame prediction step. */
  predict({ mean, covariance }: KalmanState): KalmanState {
    const h = mean[3];
    const std = [
      STD_WEIGHT_POSITION * h, STD_WEIGHT_POSITION * h, 1e-2, STD_WEIGHT_POSITION * h,
      STD_WEIGHT_VELOCITY * h, STD_WEIGHT_VELOCITY * h, 1e-5, STD_WEIGHT_VELOCITY * h,
    ];
    const predictedMean = MOTION.map((row) => row.reduce((sum, value, index) => sum + value * mean[index], 0));
    const predictedCovariance = multiply(multiply(MOTION, covariance), MOTION_T);
    std.forEach((value, index) => (predictedCovariance[index][index] += value * value));
    return { mean: predictedMean, covariance: predictedCovariance };
  },

  /** Projection into measurement space: mean (4) and innovation covariance (4x4). */
  project({ mean, covariance }: KalmanState): { mean: Vector; covariance: Matrix } {
    const h = mean[3];
    const std = [STD_WEIGHT_POSITION * h, STD_WEIGHT_POSITION * h, 1e-1, STD_WEIGHT_POSITION * h];
    const projected = covariance.slice(0, NDIM).map((row) => row.slice(0, NDIM));
    std.forEach((value, index) => (projected[index][index] += value * value));
    return { mean: mean.slice(0, NDIM), covariance: projected };
  },

  /** Correction step with a measurement (x, y, a, h). */
  update(state: KalmanState, measurement: Vector): KalmanState {
    const projected = kalmanFilter.project(state);
    // K = P[:, :4] S^-1, computed as solve(S, P[:, :4]^T)^T exactly like the NumPy reference.
    const crossCovariance = state.covariance.map((row) => row.slice(0, NDIM));
    const gain = transpose(solve(projected.covariance, transpose(crossCovariance)));
    const innovation = measurement.map((value, index) => value - projected.mean[index]);
    const mean = state.mean.map((value, row) => value + gain[row].reduce((sum, g, k) => sum + g * innovation[k], 0));
    const correction = multiply(multiply(gain, projected.covariance), transpose(gain));
    const covariance = state.covariance.map((row, i) => row.map((value, j) => value - correction[i][j]));
    return { mean, covariance };
  },
};
