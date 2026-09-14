# Transporte URBS Ingestor

Ingestor de dados abertos da URBS (Curitiba) — baixa, transforma e carrega no Postgres via Docker + Alembic.

## 🐳 Docker (Postgres)

```bash
cd /mnt/shared/jhonatan/Development/transporte-urbs-ingestor
docker compose up -d
```

| Configuração     | Valor                              |
|------------------|------------------------------------|
| **Host**         | 192.168.2.200                      |
| **Porta**        | 5432                               |
| **Banco**        | urbs_db                            |
| **Usuário**      | urbs_user (vinda do .env)          |
| **Rede**         | 192.168.2.0/24 (interna somente)  |
| **Volume**       | `urbs_pg_data` (nomeado, não bind) |

> O container **não expõe a porta 5432 externamente**. Apenas dispositivos na rede local `192.168.2.x` podem conectar.

### Conexão do cliente (desktop → container)

```
psql -h 192.168.2.200 -p 5432 -U urbs_user -d urbs_db
```

## 📦 Migrations (Alembic)

### Instalar dependências (modo desenvolvimento)

```bash
pip install -e .
pip install alembic psycopg2-binary
```

### Rodar migrations

```bash
alembic upgrade head
```

### Criar nova migration

```bash
alembic revision --autogenerate -m "descrição da alteração"
alembic upgrade head
```

### Reverter migration

```bash
alembic downgrade -1
# ou
alembic downgrade base
```

## 📄 Schema inicial

- **linhas** — linhas de ônibus (código, nome, origem, destino, cor)
- **pontos** — pontos de parada (código, lat/lng, descrição, linha_id)
- **horarios** — horários de passagem por ponto (dia_semana, hora)

## 🔐 Variáveis de ambiente

Copie `.env.example` para `.env`:

```bash
cp .env.example .env
```

Edite `.env` com as credenciais reais antes de subir o container ou rodar migrations.