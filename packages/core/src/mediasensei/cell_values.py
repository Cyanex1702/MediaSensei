"""Hashable comparison values without rewriting nested source cells."""
import numpy as np
import pandas as pd


def comparison_value(value):
    if isinstance(value, dict):
        return ("object", tuple(sorted((str(k), comparison_value(v)) for k, v in value.items())))
    if isinstance(value, (list, tuple, np.ndarray)):
        return ("array", tuple(comparison_value(v) for v in value))
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return None
    return value


def comparison_frame(frame):
    result = frame.copy(deep=False)
    for column in frame:
        if pd.api.types.is_object_dtype(frame[column]):
            result[column] = frame[column].map(comparison_value)
    return result
