"""
Reader: localiza e le os arquivos .xz produzidos pelo crawler.

Nao implementa logica do crawler — apenas le os arquivos de saida.
O caminho de entrada vem da variavel de ambiente CRAWLER_OUTPUT_PATH.
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import lzma

logger = logging.getLogger(__name__)


def load_xz_json(filepath: Path) -> list[dict[str, Any]]:
    """
    Descompacta um arquivo .xz e parseia o JSON interno.

    Args:
        filepath: caminho para o arquivo .xz

    Returns:
        Lista de dicionarios representando os registros JSON.

    Raises:
        json.JSONDecodeError: se o JSON interno for invalido.
        FileNotFoundError: se o arquivo nao existir.
    """
    logger.info("Loading xz file: %s", filepath)
    with lzma.open(filepath, "rt", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list):
        logger.warning(
            "File %s contains non-list JSON (type=%s). Wrapping in list.",
            filepath,
            type(data).__name__,
        )
        data = [data] if data is not None else []

    logger.info("Loaded %d records from %s", len(data), filepath.name)
    return data


def find_latest_xz_files(
    output_path: str | Path | None = None,
    file_patterns: list[str] | None = None,
) -> dict[str, Path]:
    """
    Localiza os arquivos .xz mais recentes correspondentes aos patterns.

    Args:
        output_path: diretorio onde os arquivos .xz estao. Se None,
                     usa a variavel de ambiente CRAWLER_OUTPUT_PATH.
        file_patterns: lista de substrings a buscar no nome (ex: ['linhas', 'pontosLinha']).
                       Se None, busca todos os .xz.

    Returns:
        Dict mapeando o pattern -> caminho do arquivo mais recente que contem o pattern.
        Apenas o arquivo com maior timestamp (partir do nome yyyy_mm_dd) e retornado.
    """
    if output_path is None:
        output_path = os.environ.get("CRAWLER_OUTPUT_PATH", "/tmp/crawler_downloads")

    base = Path(output_path)
    if not base.exists():
        logger.error("Crawler output path does not exist: %s", base)
        raise FileNotFoundError(f"Crawler output path not found: {base}")

    all_xz = sorted(base.glob("*.xz"), key=os.path.getmtime, reverse=True)
    if not all_xz:
        logger.error("No .xz files found in %s", base)
        raise FileNotFoundError(f"No .xz files in {base}")

    logger.info("Found %d .xz files in %s", len(all_xz), base)

    if file_patterns is None:
        # Retorna todos os arquivos mais recentes (agrupados por topico)
        return {f.stem: f for f in all_xz}

    result: dict[str, Path] = {}
    for pattern in file_patterns:
        matches = [f for f in all_xz if pattern.lower() in f.name.lower()]
        if matches:
            result[pattern] = matches[0]  # já ordenado por mtime desc
            logger.info("Latest file for '%s': %s", pattern, matches[0].name)
        else:
            logger.warning("No .xz file found matching pattern '%s'", pattern)

    return result


def extract_date_from_filename(filepath: Path) -> str | None:
    """
    Extrai a data (YYYY-MM-DD) do nome do arquivo, se presente.

    Formatos suportados:
        2026_09_14_linhas.json.xz
        2024-03-15_shapeLinha.json.xz

    Returns:
        String YYYY-MM-DD ou None se nao encontrada.
    """
    name = filepath.name
    # Try YYYY_MM_DD or YYYY-MM-DD at start
    for sep in ("_", "-"):
        prefix = name[:10]
        parts = prefix.split(sep)
        if len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[0]) == 4:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    return None