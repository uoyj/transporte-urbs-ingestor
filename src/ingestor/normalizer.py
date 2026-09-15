"""
Normalizer: transforma dados brutos do crawler em estruturas limpas.

Mapeia os campos do JSON do crawler para os modelos definidos em src/models.py.
Nao toca no banco — apenas estrutura os dados para upsert.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _parse_lat_lon(value: str) -> float | None:
    """
    Parse coordenadas do formato brasileiro ("-25,455206") para float.
    O crawler usa virgula como separador decimal.
    """
    if not value or value == "0":
        return None
    try:
        return float(value.replace(",", "."))
    except (ValueError, TypeError):
        logger.warning("Could not parse lat/lon value: %r", value)
        return None


def _extract_codigo(value: str) -> str:
    """Normaliza codigo removendo zeros a esquerda e espacos."""
    if not value:
        return ""
    return str(value).strip()


def normalize_linhas(raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normaliza dados do arquivo `linhas.json.xz` para o modelo Linha.

    Campos do crawler:
        COD (str): codigo da linha
        NOME (str): nome/desricao da linha
        SOMENTE_CARTAO (str): "S" ou "N"
        CATEGORIA_SERVICO (str): ex "CONVENCIONAL"
        NOME_COR (str): cor da linha ex "AMARELA"

    Retorna lista de dicts prontos para upsert na tabela linhas.
    """
    linhas: list[dict[str, Any]] = []
    for raw in raw_data:
        codigo = _extract_codigo(raw.get("COD", ""))
        if not codigo:
            logger.warning("Skipping linha without COD: %s", raw)
            continue

        nome = raw.get("NOME", "").strip()
        categoria = raw.get("CATEGORIA_SERVICO", "").strip()

        # origem e destino sao derivados do nome quando contem "/"
        # ex: "A. MUNHOZ / JD. BOTÂNICO" -> origem="A. MUNHOZ", destino="JD. BOTÂNICO"
        origem = None
        destino = None
        if "/" in nome:
            parts = [p.strip() for p in nome.split("/", 1)]
            origem = parts[0] if parts[0] else None
            destino = parts[1] if len(parts) > 1 and parts[1] else None

        # Mapeia nome da cor para hex
        cor = _map_cor(raw.get("NOME_COR", ""))

        # somente_cartao e categoria servicos sao mantidos como metadata extra
        # podem ser adicionados como colunas futuras

        linhas.append({
            "codigo": codigo,
            "nome": nome,
            "origem": origem,
            "destino": destino,
            "cor": cor,
        })

    logger.info("Normalized %d linhas", len(linhas))
    return linhas


def _map_cor(nome_cor: str) -> str | None:
    """Mapeia nomes de cores para hex codes."""
    cor_map = {
        "AMARELA": "#FFD700",
        "AZUL": "#0000FF",
        "VERMELHA": "#FF0000",
        "VERDE": "#008000",
        "LARANJA": "#FFA500",
        "ROXA": "#800080",
        "BRANCA": "#FFFFFF",
        "PRETA": "#000000",
    }
    if not nome_cor:
        return None
    return cor_map.get(nome_cor.strip().upper())


def normalize_pontos(raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normaliza dados do arquivo `pontosLinha.json.xz` para o modelo Ponto.

    Campos do crawler:
        NUM (str): ID unico do ponto
        NOME (str): descricaoCompleta do ponto
        LAT (str): latitude (formato brasileiro)
        LON (str): longitude (formato brasileiro)
        COD (str): codigo da linha a qual pertence

    Retorna lista de dicts prontos para upsert.
    Nota: um ponto pode pertencer a multiplas linhas. O modelo atual vincula
    ponto->linha por FK. Para suportar multiplas linhas, o ponto e associado
    apenas a uma (a primeira encontrada). A tabela linhas_pontos (N:N) pode
    ser adicionada futuramente.
    """
    pontos: list[dict[str, Any]] = []
    pontos_por_codigo: dict[str, dict[str, Any]] = {}

    for raw in raw_data:
        num = _extract_codigo(raw.get("NUM", ""))
        if not num:
            logger.warning("Skipping ponto without NUM: %s", raw)
            continue

        lat = _parse_lat_lon(raw.get("LAT", ""))
        lng = _parse_lat_lon(raw.get("LON", ""))

        codigo_linha = _extract_codigo(raw.get("COD", ""))

        if num not in pontos_por_codigo:
            pontos_por_codigo[num] = {
                "codigo": num,
                "latitude": lat,
                "longitude": lng,
                "descricao": raw.get("NOME", "").strip(),
                "linha_codigo": codigo_linha,
            }

    pontos = list(pontos_por_codigo.values())
    logger.info("Normalized %d pontos (from %d raw records)", len(pontos), len(raw_data))
    return pontos


def normalize_horarios(raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normaliza dados do arquivo `tabelaLinha.json.xz` para o modelo Horario.

    Campos do crawler:
        HORA (str): hora de passagem ex "05:45"
        PONTO (str): nome do ponto
        DIA (str): dia da semana (1=segunda, 2=terca, etc.)
        NUM (str): ID do ponto (referencia a pontosLinha.NUM)
        COD (str): codigo da linha

    Retorna lista de dicts prontos para upsert.
    """
    horarios: list[dict[str, Any]] = []
    for raw in raw_data:
        ponto_codigo = _extract_codigo(raw.get("NUM", ""))
        if not ponto_codigo:
            logger.debug("Skipping horario without NUM: %s", raw)
            continue

        hora = raw.get("HORA", "").strip()
        if not hora:
            logger.debug("Skipping horario without HORA: %s", raw)
            continue

        dia_semana = raw.get("DIA", "").strip()
        if not dia_semana:
            logger.debug("Skipping horario without DIA: %s", raw)
            continue

        horarios.append({
            "ponto_codigo": ponto_codigo,
            "dia_semana": dia_semana,
            "hora": hora,
        })

    logger.info("Normalized %d horarios", len(horarios))
    return horarios