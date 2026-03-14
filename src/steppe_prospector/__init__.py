"""Starter package for a safe-by-design Mongolian prospection MVP."""

from .config import load_settings
from .pipeline import MongoliaProspectionPipeline

__all__ = ["load_settings", "MongoliaProspectionPipeline"]
