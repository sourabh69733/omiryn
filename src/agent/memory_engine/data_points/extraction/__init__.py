"""Owns all selectable data-point extraction strategies and their capture policy.

Only the registry decides which conversation strategy is active. Individual extractors
produce candidates, while normalization and storage remain shared by the parent package.
"""

from .registry import DataPointCapturePolicy, data_point_capture_policy

__all__ = [
    "DataPointCapturePolicy",
    "data_point_capture_policy",
]
