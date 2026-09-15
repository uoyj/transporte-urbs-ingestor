# Transporte URBS Ingestor

Ingestor de dados abertos da URBS (Curitiba) — **fetch** + **load** de dados via crawler, normalização e upsert idempotente no Postgres via Docker + Alembic.

## 🏗️ Arquitetura (Fluxo Completo)

```
[ Crawler curitibaurbs ]          <-- fetch_step (subprocess)
         |
         |  (download-repo --date YYYY-MM-DD --dir downloads/)
         v
[ arquivos .xz/.json ]
         |
         |  CRAWLER_OUTPUT_PATH
         v
[ Ingestor (src/ingestor/) ]      <-- load_step: parse + normaliza + upsert
         |
         v
[ Postgres (URBS) ]
         |
         |  tabelas:
         |  linhas
         |  pontos
         |  horarios
         |  alembic_version
```

O ingestor roda como **um único job diário** no container `app` (não são dois containers separados). Internamente, o job é dividido em dois passos isolados:

| Passo       | Função             | Descrição                                        |
|-------------|--------------------|--------------------------------------------------|
| `fetch_step` | `scheduler.py`     | Chama crawler via subprocess, baixa `.xz`         |
| `load_step`  | `scheduler.py`     | Lê `.xz`, normaliza e aplica upsert no banco      |

Se `fetch_step` falha, `load_step` **não roda** (abortado).

## 🐳 Docker

```bash
cd /mnt/shared/jhonatan/Development/transporte-urbs-ingestor
docker compose up -d
```

| Configuração     | Valor                              |
|------------------|------------------------------------|
| **Host**         | 192.168.2.114 (LXC urbs-db-dev)    |
| **Porta**        | 5432                               |
| **Banco**        | urbs_db                            |
| **Usuário**      | urbs_user (vinda do .env)          |
| **Rede Docker**  | 172.28.0.0/16 (nao colide com LAN) |
| **Volume**       | `urbs_pg_data` (nomeado)           |

### Serviços

| Serviço     | Descrição                                              |
|-------------|--------------------------------------------------------|
| `app`       | Ingestor (fetch + load + scheduler diario)             |
| `postgres`  | Banco de dados Postgres 16-alpine                      |

### Conexão do cliente (desktop → LXC 114)

```
psql -h 192.168.2.114 -p 5432 -U urbs_user -d urbs_db
```

## 📦 Migrations (Alembic)

### Rodar migrations (via container)

```bash
docker compose run --rm --entrypoint alembic app upgrade head
```

### Criar nova migration

```bash
docker compose run --rm --entrypoint alembic app revision --autogenerate -m "descricao da alteracao"
docker compose run --rm --entrypoint alembic app upgrade head
```

### Reverter migration

```bash
docker compose run --rm --entrypoint alembic app downgrade -1
```

## 🤖 Ingestor (Fetch + Load)

### Modos de execução

```bash
# Scheduler diario (entrypoint default do container)
docker compose up -d

# Execucao unica completa (fetch + load)
docker compose run --rm --entrypoint python app -m src.ingestor --once

# Apenas fetch (rebaixar dados do dia)
docker compose run --rm --entrypoint python app -m src.ingestor --fetch-only --date "2026-09-14"

# Apenas load (processar arquivos ja baixados, sem rebaixar)
docker compose run --rm --entrypoint python app -m src.ingestor --load-only
```

### Como funciona

**fetch_step():**
- Executa: `python -m crawler_dadosabertos_cwb.main download-repo --repo curitibaurbs --date <hoje> --dir <downloads>`
- Aguarda conclusao e verifica codigo de saida
- Retorna sucesso/falha + contagem de arquivos baixados
- Se falhar, load_step e abortado

**load_step():**
- Lê os arquivos `.xz` mais recentes do `CRAWLER_OUTPUT_PATH`
- Descompacta e parseia o JSON interno
- Normaliza para estruturas limpas (linhas, pontos, horarios)
- Aplica **upsert idempotente** no banco (insert ou update pela chave natural)
- Rodar varias vezes no mesmo dia nao gera duplicatas

### Agendamento automatico

```
INGESTION_SCHEDULE=02:00  (formato HH:MM)
```

O scheduler roda como `ENTRYPOINT` do Dockerfile — **nao usa cron do SO**.
Basta `docker compose up -d` e o job roda 1x/dia no horario configurado.

### Logging

Cada execucao loga:
- Timestamp (asctime)
- Level (INFO/ERROR)
- Modulo (fetch_step/load_step/scheduler)
- Contagem de registros inseridos/atualizados
- Qualquer erro de parsing ou conexao com o banco

Logs visiveis via:
```bash
docker compose logs app -f
```

## 📄 Schema

- **linhas** — linhas de onibus (codigo, nome, origem, destino, cor)
- **pontos** — pontos de parada (codigo, lat/lng, descricao, linha_id)
- **horarios** — horarios de passagem por ponto (dia_semana, hora)

Mapeamento dos campos do crawler:
- `linhas.json.xz` → tabela **linhas**
- `pontosLinha.json.xz` → tabela **pontos**
- `tabelaLinha.json.xz` → tabela **horarios**

## 🔐 Variaveis de ambiente

Copie `.env.example` para `.env`:

```bash
cp .env.example .env
```

| Variavel              | Default                                         | Descricao                              |
|-----------------------|-------------------------------------------------|----------------------------------------|
| `POSTGRES_USER`       | `urbs_user`                                     | Usuario do Postgres                    |
| `POSTGRES_PASSWORD`   | `change_me_in_production`                       | Senha do Postgres                      |
| `POSTGRES_DB`         | `urbs_db`                                       | Nome do banco                          |
| `POSTGRES_HOST`       | `postgres`                                      | Hostname (no Docker)                   |
| `POSTGRES_PORT`       | `5432`                                          | Porta do Postgres                      |
| `CRAWLER_DIR`         | `/mnt/shared/.../crawler-dadosabertos-cwb`      | Onde o codigo do crawler esta          |
| `CRAWLER_OUTPUT_PATH` | `/mnt/shared/.../crawler-dadosabertos-cwb/downloads` | Onde os `.xz` sao salvos/lidos   |
| `INGESTION_SCHEDULE`  | `02:00`                                         | Horario diario da ingestao (HH:MM)     |