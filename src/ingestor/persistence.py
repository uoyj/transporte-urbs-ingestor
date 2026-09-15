"""
Persistence: aplica dados normalizados no banco via upsert idempotente.

Usa SQLAlchemy Core + PostgreSQL ON CONFLICT para upsert em batch.
Rodar o ingestor varias vezes no mesmo dia nao gera duplicatas.
"""

import logging
import os
from typing import Any
from sqlalchemy import create_engine, insert, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from src.models import Linha, Ponto, Horario, Base

logger = logging.getLogger(__name__)

# Chunk size para batch inserts (evita queries muito grandes)
BATCH_SIZE = 5000


def _make_engine(db_url: str) -> Any:
    """Cria engine SQLAlchemy a partir da URL de conexao."""
    return create_engine(db_url, echo=False, future=True)


def _get_db_url() -> str:
    """Constrói URL de conexao usando variaveis de ambiente."""
    user = os.environ.get("POSTGRES_USER", "urbs_user")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "urbs_db")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def _chunked(data: list, size: int):
    """Yield chunks de `size` elementos da lista `data`."""
    for i in range(0, len(data), size):
        yield data[i:i + size]


def upsert_linhas(engine: Any, linhas_data: list[dict[str, Any]]) -> int:
    """
    Upsert de linhas na tabela `linhas` via batch ON CONFLICT.

    Chave natural: codigo (unico).
    Returns: numero de registros inseridos/atualizados.
    """
    if not linhas_data:
        return 0

    total = 0
    with engine.begin() as conn:
        for chunk in _chunked(linhas_data, BATCH_SIZE):
            stmt = pg_insert(Linha.__table__).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["codigo"],
                set_={
                    "nome": stmt.excluded.nome,
                    "origem": stmt.excluded.origem,
                    "destino": stmt.excluded.destino,
                    "cor": stmt.excluded.cor,
                },
            )
            result = conn.execute(stmt)
            total += result.rowcount

    logger.info("Upserted %d linhas", total)
    return total


def upsert_pontos(
    engine: Any,
    pontos_data: list[dict[str, Any]],
) -> int:
    """
    Upsert de pontos na tabela `pontos` via batch ON CONFLICT.

    Chave natural: codigo do ponto.
    linha_id e resolvido previamente (via batch de lookup).

    Para cada ponto, tenta resolver a linha_id pelo codigo.
    Se a linha nao existir, linha_id fica NULL.
    """
    if not pontos_data:
        return 0

    # Pre-fetches: resolve linha_ids via codigo (single query)
    pontos_com_linha: list[dict[str, Any]] = []
    linha_codigos = {p["linha_codigo"] for p in pontos_data if p.get("linha_codigo")}

    with engine.connect() as conn:
        linha_map_query = text(
            "SELECT codigo, id FROM linhas WHERE codigo = ANY(:codigos)"
        )
        rows = conn.execute(linha_map_query, {"codigos": list(linha_codigos)}).fetchall()
        linha_map = {str(row[0]): row[1] for row in rows}

    for ponto in pontos_data:
        linha_codigo = ponto.get("linha_codigo", "")
        linha_id = linha_map.get(linha_codigo) if linha_codigo else None
        if linha_codigo and not linha_id:
            logger.debug(
                "Linha codigo=%s not found for ponto codigo=%s",
                linha_codigo, ponto.get("codigo"),
            )
        pontos_com_linha.append({
            "codigo": ponto["codigo"],
            "latitude": ponto["latitude"],
            "longitude": ponto["longitude"],
            "descricao": ponto["descricao"],
            "linha_id": linha_id,
        })

    total = 0
    with engine.begin() as conn:
        for chunk in _chunked(pontos_com_linha, BATCH_SIZE):
            stmt = pg_insert(Ponto.__table__).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["codigo"],
                set_={
                    "latitude": stmt.excluded.latitude,
                    "longitude": stmt.excluded.longitude,
                    "descricao": stmt.excluded.descricao,
                    "linha_id": stmt.excluded.linha_id,
                },
            )
            result = conn.execute(stmt)
            total += result.rowcount

    logger.info("Upserted %d pontos", total)
    return total


def upsert_horarios(
    engine: Any,
    horarios_data: list[dict[str, Any]],
) -> int:
    """
    Upsert de horarios na tabela `horarios` via batch ON CONFLICT DO NOTHING.

    Resolve ponto_id via codigo do ponto (NUM no crawler).
    Usa ON CONFLICT (ponto_id, dia_semana, hora) DO NOTHING para idempotencia.

    Returns: numero de registros inseridos.
    """
    if not horarios_data:
        return 0

    # Pre-fetch: resolve ponto_ids via codigo (single query)
    ponto_codigos = list({h["ponto_codigo"] for h in horarios_data if h.get("ponto_codigo")})

    with engine.connect() as conn:
        ponto_map_query = text(
            "SELECT codigo, id FROM pontos WHERE codigo = ANY(:codigos)"
        )
        rows = conn.execute(ponto_map_query, {"codigos": ponto_codigos}).fetchall()
        ponto_map = {str(row[0]): row[1] for row in rows}

    # Filter out horarios whose ponto_codigo doesn't exist
    valid_horarios: list[dict[str, Any]] = []
    skipped = 0
    for h in horarios_data:
        ponto_codigo = h.get("ponto_codigo", "")
        ponto_id = ponto_map.get(ponto_codigo) if ponto_codigo else None
        if not ponto_id:
            skipped += 1
            logger.debug("Ponto codigo=%s not found for horario. Skipping.", ponto_codigo)
            continue
        valid_horarios.append({
            "ponto_id": ponto_id,
            "dia_semana": h["dia_semana"],
            "hora": h["hora"],
        })

    if skipped > 0:
        logger.info("Skipped %d horarios (ponto not found)", skipped)

    if not valid_horarios:
        logger.info("No valid horarios to upsert")
        return 0

    total = 0
    with engine.begin() as conn:
        for chunk in _chunked(valid_horarios, BATCH_SIZE):
            stmt = pg_insert(Horario.__table__).values(chunk)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["ponto_id", "dia_semana", "hora"],
            )
            result = conn.execute(stmt)
            total += result.rowcount

    logger.info(
        "Upserted %d horarios (%d skipped as duplicate)",
        total,
        skipped,
    )
    return total


def get_session() -> Session:
    """Factory para obter uma sessao SQLAlchemy usando env vars."""
    engine = _make_engine(_get_db_url())
    SessionLocal = sessionmaker(bind=engine, future=True)
    return SessionLocal()