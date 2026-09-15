"""
Scheduler: agendador leve em Python puro.

Roda como processo principal no container. A rotina de ingestao e composta
por dois passos isolados:

    1. fetch_step()   — chama o crawler via subprocess, baixa arquivos .xz/.json
    2. load_step()    — le os arquivos baixados, normaliza e aplica upsert no banco

Ambos podem ser chamados isoladamente. O job diario (via INGESTION_SCHEDULE,
formato "HH:MM", default "02:00") executa fetch_step seguido de load_step.
Se fetch_step falhar, load_step eh abortado.

Uso:
    # Scheduler diario (entrypoint do container):
    python -m src.ingestor

    # Execucao unica (para testes manuais):
    python -m src.ingestor --once

    # Apenas fetch (rebaixar dados):
    python -m src.ingestor --fetch-only --date "2026-09-14"

    # Apenas load (processar arquivos ja baixados):
    python -m src.ingestor --load-only
"""

import logging
import os
import time
import datetime
import signal
import sys
import subprocess
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default schedule: 02:00
DEFAULT_SCHEDULE = "02:00"

# Timezone: Brasil (America/Sao_Paulo) — o schedule INGESTION_SCHEDULE
# eh interpretado nesse TZ, nao no UTC do container.
try:
    from zoneinfo import ZoneInfo
    BRT = ZoneInfo("America/Sao_Paulo")
except ImportError:  # pragma: no cover — Python < 3.9 fallback
    from backports.zoneinfo import ZoneInfo  # type: ignore
    BRT = ZoneInfo("America/Sao_Paulo")

# File patterns to look for in crawler output
FILE_PATTERNS = ["linhas", "pontosLinha", "tabelaLinha"]

# Crawler config
CRAWLER_MODULE = "crawler_dadosabertos_cwb.main"
CRAWLER_REPO = "curitibaurbs"
DEFAULT_CRAWLER_DIR = "/mnt/shared/jhonatan/Development/crawler-dadosabertos-cwb/downloads"


def _parse_schedule(schedule: str) -> tuple[int, int]:
    """Parse 'HH:MM' -> (hour, minute)."""
    parts = schedule.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid schedule format '{schedule}'. Use HH:MM.")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid hour/minute in schedule '{schedule}'.")
    return hour, minute


def _seconds_until_next(target_hour: int, target_minute: int) -> tuple[int, str]:
    """Calcula segundos ate o proximo horario alvo (hoje ou amanha) no TZ Brasil.

    Returns:
        (seconds, next_run_utc_str) — segundos ate o proximo disparo e
        string ISO do proximo horario agendado (em BRT).
    """
    now = datetime.datetime.now(tz=BRT)
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    if target <= now:
        target += datetime.timedelta(days=1)

    delta = (target - now).total_seconds()
    return int(delta), target.isoformat()


def _today_date_str() -> str:
    """Retorna a data de hoje no formato YYYY-MM-DD (timezone America/Sao_Paulo)."""
    return datetime.datetime.now(tz=BRT).date().isoformat()


def fetch_step(
    date: str | None = None,
    output_dir: str | None = None,
    crawler_module: str = CRAWLER_MODULE,
    repo: str = CRAWLER_REPO,
) -> dict[str, Any]:
    """
    Passo 1: chama o crawler via subprocess para baixar arquivos .xz/.json.

    Executa: python -m crawler_dadosabertos_cwb.main download-repo --repo curitibaurbs --date <data> --dir <destino>

    Args:
        date: data no formato YYYY-MM-DD. Se None, usa hoje.
        output_dir: diretorio onde salvar os arquivos. Se None, usa CRAWLER_OUTPUT_PATH.
        crawler_module: module Python do crawler.
        repo: repositorio C3SL (default: curitibaurbs).

    Returns:
        Dict: {success: bool, date: str, files_downloaded: int, output_dir: str, error: str|None}
    """
    if date is None:
        date = _today_date_str()

    if output_dir is None:
        output_dir = os.environ.get(
            "CRAWLER_OUTPUT_PATH",
            DEFAULT_CRAWLER_DIR,
        )

    output_dir_abs = str(Path(output_dir).expanduser().resolve())
    os.makedirs(output_dir_abs, exist_ok=True)

    logger.info("fetch_step: iniciado para data=%s, repo=%s, dir=%s", date, repo, output_dir_abs)

    cmd = [
        sys.executable, "-m", crawler_module,
        "download-repo",
        "--repo", repo,
        "--date", date,
        "--dir", output_dir_abs,
    ]

    logger.info("fetch_step: executando: %s", " ".join(cmd))
    result = {
        "success": False,
        "date": date,
        "files_downloaded": 0,
        "output_dir": output_dir_abs,
        "error": None,
    }

    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutos
        )

        if process.returncode != 0:
            logger.error(
                "fetch_step: crawler falhou (exit=%d): %s",
                process.returncode,
                process.stderr.strip()[:500],
            )
            result["error"] = f"crawler exit={process.returncode}: {process.stderr.strip()[:300]}"
            return result

        # Conta arquivos .xz baixados na data
        downloaded = list(Path(output_dir_abs).glob(f"{date.replace('-', '_')}*.xz"))
        result["files_downloaded"] = len(downloaded)

        if len(downloaded) == 0:
            logger.error(
                "fetch_step: crawler exit=0 pero 0 arquivos .xz baixados. "
                "Data invalida ou sem dados."
            )
            result["success"] = False
            result["error"] = "crawler exit=0 but 0 files downloaded (date may be wrong or no data)"
            return result

        result["success"] = True

        logger.info(
            "fetch_step: sucesso. %d arquivo(s) .xz baixados para %s",
            result["files_downloaded"], output_dir_abs,
        )
        return result

    except subprocess.TimeoutExpired:
        logger.error("fetch_step: crawler timed out after 600s")
        result["error"] = "crawler timed out after 600s"
        return result
    except FileNotFoundError:
        logger.error("fetch_step: crawler module not found (%s)", crawler_module)
        result["error"] = f"crawler module '{crawler_module}' not found"
        return result
    except Exception as e:
        logger.error("fetch_step: unexpected error: %s", e)
        result["error"] = str(e)
        return result


def load_step(
    crawler_output_path: str | None = None,
    db_url: str | None = None,
) -> dict[str, int]:
    """
    Passo 2: le os arquivos .xz baixados pelo fetch_step, normaliza e aplica upsert.

    Args:
        crawler_output_path: diretorio onde os .xz estao. Se None, usa CRAWLER_OUTPUT_PATH.
        db_url: URL de conexao. Se None, derivado de env vars.

    Returns:
        Dict com contagens: {linhas, pontos, horarios, total_files_processed}
    """
    # Lazy import para que load_step so carregue persistence quando chamado
    from .reader import find_latest_xz_files, load_xz_json
    from .normalizer import normalize_linhas, normalize_pontos, normalize_horarios
    from .persistence import _get_db_url, _make_engine, upsert_linhas, upsert_pontos, upsert_horarios

    logger.info("load_step: iniciado")

    crawler_path = crawler_output_path or os.environ.get(
        "CRAWLER_OUTPUT_PATH",
        DEFAULT_CRAWLER_DIR,
    )

    result: dict[str, int] = {
        "linhas": 0,
        "pontos": 0,
        "horarios": 0,
        "total_files_processed": 0,
    }

    db_url_final = db_url or _get_db_url()
    engine = _make_engine(db_url_final)
    logger.info("load_step: database engine configured")

    # Find latest .xz files
    try:
        files = find_latest_xz_files(crawler_path, file_patterns=FILE_PATTERNS)
    except FileNotFoundError:
        logger.error("load_step: No crawler output files found in %s", crawler_path)
        return result

    if not files:
        logger.error("load_step: No crawler output files found in %s", crawler_path)
        return result

    result["total_files_processed"] = len(files)

    for pattern, filepath in files.items():
        logger.info("load_step: processing '%s' -> %s", pattern, filepath.name)
        try:
            raw_data = load_xz_json(filepath)
        except Exception as e:
            logger.error("load_step: failed to load %s: %s", filepath, e)
            continue

        if pattern == "linhas":
            linhas_data = normalize_linhas(raw_data)
            result["linhas"] = upsert_linhas(engine, linhas_data)

        elif pattern == "pontosLinha":
            pontos_data = normalize_pontos(raw_data)
            result["pontos"] = upsert_pontos(engine, pontos_data)

        elif pattern == "tabelaLinha":
            horarios_data = normalize_horarios(raw_data)
            result["horarios"] = upsert_horarios(engine, horarios_data)

    logger.info(
        "load_step: concluido: %d linhas, %d pontos, %d horarios",
        result["linhas"], result["pontos"], result["horarios"],
    )
    return result


def run_ingestion(
    date: str | None = None,
    fetch: bool = True,
    load: bool = True,
) -> dict[str, Any]:
    """
    Executa o job completo: fetch_step -> load_step.

    Se fetch falhar, load_step nao roda (abortado).

    Args:
        date: data para o fetch_step. Se None, usa hoje.
        fetch: se True, roda fetch_step.
        load: se True, roda load_step (so roda se fetch deu certo ou se fetch=False).

    Returns:
        Dict com resultado combinado.
    """
    combined: dict[str, Any] = {
        "fetch": None,
        "load": None,
        "overall_success": False,
    }

    if fetch:
        logger.info("=== Ingestao: FETCH STEP ===")
        fetch_result = fetch_step(date=date)
        combined["fetch"] = fetch_result

        if not fetch_result["success"]:
            logger.error(
                "=== Ingestao ABORTADA: fetch_step falhou (%s). load_step NAO executado. ===",
                fetch_result["error"],
            )
            combined["overall_success"] = False
            return combined

        if fetch_result.get("files_downloaded", 0) == 0:
            logger.warning("=== Ingestao: fetch_step sucesso mas 0 arquivos baixados ===")

    if load:
        logger.info("=== Ingestao: LOAD STEP ===")
        load_result = load_step()
        combined["load"] = load_result

    combined["overall_success"] = True
    logger.info("=== Ingestao concluida ===")
    return combined


def main():
    """Entry point do scheduler.

    Args:
        --once          : roda ingestao uma vez e sai.
        --fetch-only     : so roda fetch_step (com --date opcional).
        --load-only      : so roda load_step.
        --date YYYY-MM-DD: data para fetch_step (default: hoje).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Parse args manually (sem depender de argparse para manter simples)
    run_once = "--once" in sys.argv
    fetch_only = "--fetch-only" in sys.argv
    load_only = "--load-only" in sys.argv

    # --fetch-only e --load-only implicam --once (nao faz sentido no modo scheduler)
    if fetch_only or load_only:
        run_once = True

    date_arg = None
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            date_arg = sys.argv[idx + 1]

    # Handle graceful shutdown — interrompe o sleep e sai limpo
    shutdown_event = threading.Event()

    def _signal_handler(signum, frame):
        logger.info("Received signal %s, shutting down gracefully.", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # --- Modo manual (para testes) ---
    if run_once:
        logger.info("Running single ingestion (--once mode)")
        result = run_ingestion(
            date=date_arg,
            fetch=not load_only,
            load=not fetch_only,
        )
        print(f"\n=== Resultado da ingestao ===")
        if result.get("fetch"):
            f = result["fetch"]
            print(f"  Fetch: success={f['success']}, files={f['files_downloaded']}, date={f['date']}")
            if f.get("error"):
                print(f"  Fetch error: {f['error']}")
        if result.get("load"):
            l = result["load"]
            print(f"  Load: linhas={l['linhas']}, pontos={l['pontos']}, horarios={l['horarios']}")
            print(f"  Files processed: {l['total_files_processed']}")
        print(f"  Overall: {'SUCCESS' if result.get('overall_success') else 'FAILED'}")
        return

    # --- Modo agendado (scheduler) ---
    schedule_str = os.environ.get("INGESTION_SCHEDULE", DEFAULT_SCHEDULE)
    hour, minute = _parse_schedule(schedule_str)
    logger.info(
        "Scheduler started. Ingestion schedule: daily at %02d:%02d (timezone: America/Sao_Paulo)",
        hour, minute,
    )

    # Run once immediately on startup
    logger.info("Running initial ingestion on startup...")
    try:
        result = run_ingestion()
        logger.info("Initial ingestion complete: %s", str(result))
    except Exception as e:
        logger.error("Initial ingestion failed: %s", e, exc_info=True)

    # Loop forever
    while not shutdown_event.is_set():
        seconds, next_run = _seconds_until_next(hour, minute)
        logger.info(
            "Next scheduled ingestion at %s (in %d seconds) — timezone: America/Sao_Paulo",
            next_run, seconds,
        )
        # shutdown_event.wait permite interrupcao graciosa via SIGTERM/SIGINT
        if shutdown_event.wait(timeout=seconds):
            logger.info("Shutdown signal received during sleep. Exiting loop.")
            break

        logger.info("=== SCHEDULED INGESTION STARTING ===")
        try:
            result = run_ingestion()
            logger.info("=== SCHEDULED INGESTION COMPLETE: %s ===", str(result))
        except Exception as e:
            logger.error(
                "=== SCHEDULED INGESTION FAILED: %s ===", e, exc_info=True,
            )
            logger.info("Error handled — process continues. Next run will proceed as scheduled.")