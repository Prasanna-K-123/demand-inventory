"""Input contracts for the historical forecast and weekly inventory APIs.

NaN prices represent unavailable prices. Missing sales are never interpreted
as zero demand. The simulator advances one seven-day period per origin.
"""
import numpy as np


def scalar(value, name, *, minimum=0.0, maximum=None):
    raw = np.asarray(value)
    if raw.ndim != 0 or raw.dtype.kind not in 'iuf':
        raise ValueError(f'{name} must be a finite real scalar')
    number = float(raw)
    if not np.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
        raise ValueError(f'{name} is outside its finite domain')
    return number


def integer(value, name, *, minimum):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f'{name} must be an integer of at least {minimum}')
    return int(value)


def numbers(value, name, *, ndim, missing=False, nonnegative=True):
    raw = np.asarray(value)
    if raw.ndim != ndim or raw.dtype.kind not in 'iuf':
        raise ValueError(f'{name} must be a real {ndim}-dimensional array')
    array = np.asarray(raw, dtype=float)
    if np.isinf(array).any() or (not missing and np.isnan(array).any()):
        raise ValueError(f'{name} contains nonfinite values')
    if nonnegative and np.any(array < 0):
        raise ValueError(f'{name} must be nonnegative')
    return array


def identifiers(value, n):
    keys = np.asarray(value)
    if keys.ndim != 1 or len(keys) != n:
        raise ValueError('Series identifiers must align with the series')
    if keys.dtype.kind in 'iuf':
        if not np.isfinite(keys).all():
            raise ValueError('Numerical series identifiers must be finite')
    elif keys.dtype.kind in 'USO':
        if not all(isinstance(x, str) and x.strip() for x in keys):
            raise ValueError('Series identifiers must be nonempty strings or real numbers')
    else:
        raise ValueError('Unsupported series identifiers')
    if len(set(str(x) for x in keys)) != n:
        raise ValueError('Series identifiers must be unique for deterministic tie breaks')
    return keys


def sba_inputs(sales, alpha):
    history = numbers(sales, 'Sales history', ndim=1)
    smoothing = scalar(alpha, 'SBA smoothing', minimum=0.0, maximum=1.0)
    if not 0.0 < smoothing < 1.0:
        raise ValueError('SBA smoothing must lie strictly between zero and one')
    return history, smoothing


def target_inputs(sales, origin, horizon):
    panel = numbers(sales, 'Sales panel', ndim=2)
    start = integer(origin, 'Target origin', minimum=0)
    length = integer(horizon, 'Target horizon', minimum=1)
    if panel.shape[0] == 0 or start + length > panel.shape[1]:
        raise ValueError('Target window must be fully observed')
    return panel, start, length


def allocation_inputs(desired, cost, penalty, coverage, ids, budget, capacity):
    desired = numbers(desired, 'Desired orders', ndim=1)
    cost = numbers(cost, 'Unit cost', ndim=1, missing=True)
    penalty = numbers(penalty, 'Shortage penalty', ndim=1, missing=True)
    coverage = numbers(coverage, 'Stock coverage', ndim=1)
    if not all(len(x) == len(desired) for x in [cost, penalty, coverage]):
        raise ValueError('Allocation vectors must have the same length')
    keys = identifiers(ids, len(desired))
    known = np.isfinite(cost) & (cost > 0)
    if not np.isfinite(penalty[known]).all():
        raise ValueError('An orderable series needs a finite shortage penalty')
    budget = scalar(budget, 'Budget')
    capacity = scalar(capacity, 'Capacity')
    return desired, cost, penalty, coverage, keys, budget, capacity


def simulation_inputs(sales, price, origins, quantiles, ids, budget_multiplier,
                      lead_weeks, shortage_fraction, censor):
    sales = numbers(sales, 'Sales panel', ndim=2)
    price = numbers(price, 'Price panel', ndim=2, missing=True)
    if sales.shape != price.shape or sales.shape[0] == 0:
        raise ValueError('Sales and prices must be aligned, nonempty panels')
    if np.any(price[np.isfinite(price)] <= 0):
        raise ValueError('Observed prices must be positive; use NaN for unavailable prices')
    keys = identifiers(ids, sales.shape[0])
    dates = np.asarray(origins)
    if dates.ndim != 1 or dates.dtype.kind not in 'iu' or len(dates) == 0:
        raise ValueError('Simulation origins must be a nonempty integer vector')
    if np.any(dates < 28) or np.any(dates > sales.shape[1] - 7):
        raise ValueError('Origins must be consecutive seven-day periods with 28 prior and seven future days')
    # Bounds are checked before conversion: unsigned values outside int64 cannot
    # wrap into range. Compute differences in a signed, full-width type.
    dates = dates.astype(np.int64, copy=False)
    if np.any(np.diff(dates) != 7):
        raise ValueError('Origins must be consecutive seven-day periods with 28 prior and seven future days')
    forecasts = numbers(quantiles, 'Forecast quantiles', ndim=3)
    if forecasts.shape != (len(dates), len(keys), 4) or np.any(np.diff(forecasts, axis=2) < 0):
        raise ValueError('Need four ordered quantiles per origin and series')
    budget_multiplier = scalar(budget_multiplier, 'Budget multiplier')
    lead_weeks = integer(lead_weeks, 'Lead time in weeks', minimum=1)
    shortage_fraction = scalar(shortage_fraction, 'Shortage fraction')
    if not isinstance(censor, (bool, np.bool_)):
        raise ValueError('Censoring proxy switch must be boolean')
    return sales, price, dates, forecasts, keys, budget_multiplier, lead_weeks, shortage_fraction, bool(censor)
