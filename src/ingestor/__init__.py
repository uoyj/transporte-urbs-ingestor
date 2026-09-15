"""Módulo do ingestor: fetch_step, load_step e scheduler."""
from .reader import find_latest_xz_files, load_xz_json
from .normalizer import normalize_linhas, normalize_pontos, normalize_horarios
from .persistence import upsert_linhas, upsert_pontos, upsert_horarios
from .scheduler import run_ingestion, fetch_step, load_step, main

__all__ = [
    "find_latest_xz_files",
    "load_xz_json",
    "normalize_linhas",
    "normalize_pontos",
    "normalize_horarios",
    "upsert_linhas",
    "upsert_pontos",
    "upsert_horarios",
    "run_ingestion",
    "fetch_step",
    "load_step",
    "main",
]