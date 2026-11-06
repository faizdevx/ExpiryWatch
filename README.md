# ExpiryWatch

**Track smarter. Waste less.**

ExpiryWatch is a REST API for tracking product stock by batch, so each delivery keeps its own
expiration date. It reports what has expired, what is about to, and what to sell first.

## Problem statement

Small grocery shops, local retailers, hostels, and households often lose stock to expiry. A product
usually arrives in several deliveries with different dates, so tracking only a name and a total
quantity hides what is about to expire.

For example, a shop with 50 packets of milk may really hold:

| Batch | Quantity | Expiration date |
|---|---:|---|
| B001 | 10 | 2026-11-08 |
| B002 | 20 | 2026-11-15 |
| B003 | 20 | 2026-11-25 |

ExpiryWatch tracks each of these batches separately.

## Main features

- Product management with search, filters, and pagination
- Batch-level inventory, with independent quantities and expiration dates
- Expiration status always derived from the date, never stored
- Alerts and listings in FEFO order (First Expired, First Out)
- Dashboard summary of stock and expiry
- Barcode lookup through Open Food Facts, with manual registration always available
- API key protection for write operations
- One consistent JSON error format

## Technology stack

| Technology | Purpose |
|---|---|
| Python 3.12 | Language |
| FastAPI | REST API framework |
| PostgreSQL 17 | Database |
| SQLAlchemy 2 + psycopg 3 | ORM and database driver |
| Pydantic 2 | Request and response validation |
| Alembic | Database migrations |
| HTTPX | Asynchronous calls to the barcode provider |
| Pytest | Automated tests |
| Ruff | Linting and formatting |
| Docker + Docker Compose | Containers and local environment |
| Render | Public deployment |

The application has no AI or LLM dependency at runtime.

## Architecture overview

One FastAPI process, one PostgreSQL database, and one external API.

```text
HTTP request
  routes/       parse input with Pydantic, inject dependencies, return a schema
  services/     business rules and queries, raise AppError on failure
  models/       SQLAlchemy tables
  PostgreSQL

Any error
  exceptions/handlers.py   one JSON error format, plus server-side logging
```

- **Routes** contain no business rules or SQL.
- **Database routes** are synchronous `def` functions, which FastAPI runs in a thread pool.
- **The barcode route** is `async def`, because it waits on an external network call.
- **The database enforces integrity.** Duplicate barcodes and invalid product references are caught
  by constraints, because a check-then-insert in Python could race with another request.
- **Status is derived on every read,** so it cannot become stale.

## Database relationships

One product has many inventory batches.

```text
products 1 ──── * inventory_batches   (foreign key: ON DELETE RESTRICT)
```

**`products`:** `id`, `name`, `barcode` (unique, nullable), `brand`, `category`, `description`,
`created_at`, `updated_at`

**`inventory_batches`:** `id`, `product_id` (foreign key), `batch_number`, `quantity`
(`CHECK quantity >= 0`), `expiry_date`, `received_at`, `location`, `created_at`, `updated_at`

Indexes exist on `products.name`, `products.barcode`, `inventory_batches.product_id`, and
`inventory_batches.expiry_date`.

### Business rules

| Rule | Behavior |
|---|---|
| Expired | `expiry_date` before today |
| Expiring soon | `expiry_date` from today through today + `EXPIRY_WARNING_DAYS`, both days included |
| Safe | `expiry_date` after the warning window |
| Zero-quantity batch | Hidden from lists, alerts, and the dashboard; still readable by ID, or with `include_depleted=true` |
| Past expiration date | Accepted, so already-expired stock can be recorded |
| Moving a batch to another product | Not allowed; `product_id` cannot be changed |
| Deleting a product | Returns 409 while any batch has stock, **including expired stock**. Otherwise deletes the product and its zero-quantity batches |

## Project structure

```text
ExpiryWatch/
├── app/
│   ├── main.py              # App setup, logging, lifespan, route registration
│   ├── config.py            # Environment settings, validated at startup
│   ├── database.py          # Engine, session dependency, base model
│   ├── auth.py              # X-API-Key check
│   ├── models/              # Tables: product, batch
│   ├── schemas/             # Request and response shapes
│   ├── routes/              # products, batches, alerts, dashboard, health
│   ├── services/
│   │   ├── product_service.py
│   │   ├── batch_service.py
│   │   ├── expiry_service.py    # Status rules, "today", dashboard query
│   │   └── barcode_service.py   # Everything specific to Open Food Facts
│   └── exceptions/handlers.py   # Error types and JSON formatting
├── alembic/                 # Migrations
├── tests/
├── docs/AI_FAILURE.md       # Documented coding-agent failure
├── .env.example
├── compose.yaml
├── Dockerfile
├── render.yaml              # Render deployment Blueprint
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # Adds Pytest and Ruff
└── pyproject.toml           # Ruff and Pytest settings
```

## Quick start with Docker

You need Docker with Compose. No local Python or PostgreSQL is required.

```bash
git clone https://github.com/faizdevx/ExpiryWatch.git
```

```bash
cd ExpiryWatch
```

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

The first start can take a few minutes while PostgreSQL initializes. Then open:

- API: <http://localhost:8000>
- Swagger docs: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI schema: <http://localhost:8000/openapi.json>

Compose runs two services:

- **`db`:** PostgreSQL, published on host port **5433** to avoid clashing with a local PostgreSQL.
  Data lives in the `postgres_data` volume.
- **`api`:** the application on port 8000. It applies migrations, then starts the server.

Useful commands:

| Command | Effect |
|---|---|
| `docker compose down` | Stops and removes containers; **keeps your data** |
| `docker compose down -v` | Stops and **permanently deletes all data** |
| `docker compose logs -f api` | Follows API logs |

## Local installation without Docker for the API

You need Python 3.12 and Docker for the database. Commands below use Git Bash on Windows; on Linux
or macOS, replace `.venv/Scripts/` with `.venv/bin/`.

```bash
cp .env.example .env
```

```bash
docker compose up -d db
```

```bash
python -m venv .venv
```

```bash
.venv/Scripts/pip install -r requirements-dev.txt
```

```bash
.venv/Scripts/alembic upgrade head
```

```bash
.venv/Scripts/uvicorn app.main:app --reload
```

## Environment variables

Copy `.env.example` to `.env`. Never commit `.env`; it is ignored by Git.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Yes | None | PostgreSQL URL. `postgres://` and `postgresql://` are accepted. Compose sets its own value for the `api` container |
| `POSTGRES_PASSWORD` | For Compose | None | Database password. Use only URL-safe characters, because it goes into `DATABASE_URL` |
| `APP_ENV` | No | `development` | `development`, `test`, or `production` |
| `APP_API_KEY` | In production | None | API key for protected routes |
| `EXTERNAL_API_BASE_URL` | No | `https://world.openfoodfacts.org` | Barcode provider URL |
| `EXPIRY_WARNING_DAYS` | No | `30` | Warning window, from 0 to 3650 days |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `APP_TIMEZONE` | No | `UTC` | IANA name that decides what "today" means, such as `Asia/Kolkata` |

### Authentication

Protected routes need an `X-API-Key` header: every `POST`, `PATCH`, and `DELETE`, plus barcode
lookup, which uses a limited provider quota.

| Situation | Behavior |
|---|---|
| `APP_API_KEY` blank, not production | Protected routes are open, for local convenience |
| `APP_API_KEY` set | Header required; otherwise 401 |
| `APP_API_KEY` blank, `APP_ENV=production` | The application refuses to start |

Other read routes are public. Keys are compared in constant time and are never logged.

To generate a key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Database migrations

The Docker image applies migrations automatically on start. To run them by hand:

| Task | Command |
|---|---|
| Apply all migrations | `alembic upgrade head` |
| Show current version | `alembic current` |
| Undo all migrations (**deletes the tables**) | `alembic downgrade base` |
| Generate a migration after changing a model | `alembic revision --autogenerate -m "describe change"` |
| Check that models match migrations | `alembic check` |

## Testing

Tests need PostgreSQL but not the internet. External HTTP calls are mocked.

```bash
docker compose up -d db
```

```bash
.venv/Scripts/pytest
```

- Tests run on a separate database, named after your database with `_test` added
  (`expirywatch_test`), which is **dropped and rebuilt through Alembic on every run**.
- The suite refuses to run on any database whose name does not end in `_test`.
- To use another server, set `TEST_DATABASE_URL`. Its user must be able to create databases.
- Each test rolls back its own transaction. Concurrency tests really commit, then clean up.

To lint and format:

```bash
.venv/Scripts/ruff check .
```

```bash
.venv/Scripts/ruff format .
```

## REST API

Base path: `/api/v1`, except `/health`. Interactive documentation is at `/docs`.

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Returns 200, or 503 if the database is unreachable |

### Products

| Method | Path | Key | Description |
|---|---|---|---|
| POST | `/products` | Yes | Create a product |
| GET | `/products` | No | List. Filters: `q` (name or brand), `category`, `brand`, `barcode`, `limit`, `offset` |
| GET | `/products/{id}` | No | Get one |
| PATCH | `/products/{id}` | Yes | Update the fields sent |
| DELETE | `/products/{id}` | Yes | Delete, unless stock remains |
| GET | `/products/lookup/{barcode}` | Yes | Look up a barcode with the provider. Saves nothing |

### Batches

| Method | Path | Key | Description |
|---|---|---|---|
| POST | `/batches` | Yes | Create a batch. `received_at` defaults to today |
| GET | `/batches` | No | List. Filters: `product_id`, `expiry_status`, `expiry_from`, `expiry_to`, `location`, `include_depleted`, `sort` (`expiry_asc` or `expiry_desc`), `limit`, `offset` |
| GET | `/batches/{id}` | No | Get one |
| PATCH | `/batches/{id}` | Yes | Update the fields sent |
| DELETE | `/batches/{id}` | Yes | Delete |

Batch responses also include derived `status`, `days_until_expiry`, and `product_name`.

### Alerts

All alerts are in FEFO order, exclude zero-quantity batches, and accept `limit` and `offset`.

| Method | Path | Description |
|---|---|---|
| GET | `/alerts` | Expired and expiring-soon batches |
| GET | `/alerts/expired` | Expired batches |
| GET | `/alerts/expiring?within_days=30` | Expiring from today through today + N. Defaults to the configured window. Excludes expired |

`within_days` widens the search only. A batch's `status` still follows `EXPIRY_WARNING_DAYS`.

### Dashboard

| Method | Path | Description |
|---|---|---|
| GET | `/dashboard/summary` | Totals below |

Fields: `total_products`, `total_active_batches`, `total_units`, `expired_batches`,
`expiring_soon_batches`, `expired_units`, `expiring_soon_units`.

Totals include expired stock, because it is still physically present.

## Example curl requests

These assume a fresh database, so the first product and batch get ID 1. If you set `APP_API_KEY`, add
`-H "X-API-Key: your-key"` to the protected requests.

Create a product:

```bash
curl -X POST http://localhost:8000/api/v1/products -H "Content-Type: application/json" -d '{"name":"Milk","brand":"Amul","category":"Dairy","barcode":"12345670"}'
```

Add three batches with different dates:

```bash
curl -X POST http://localhost:8000/api/v1/batches -H "Content-Type: application/json" -d '{"product_id":1,"batch_number":"B001","quantity":10,"expiry_date":"2026-11-08","location":"Fridge"}'
```

```bash
curl -X POST http://localhost:8000/api/v1/batches -H "Content-Type: application/json" -d '{"product_id":1,"batch_number":"B002","quantity":20,"expiry_date":"2026-11-15","location":"Fridge"}'
```

```bash
curl -X POST http://localhost:8000/api/v1/batches -H "Content-Type: application/json" -d '{"product_id":1,"batch_number":"B003","quantity":20,"expiry_date":"2026-11-25","location":"Shelf"}'
```

List stock, first to expire first:

```bash
curl "http://localhost:8000/api/v1/batches?product_id=1"
```

Filter by status and location:

```bash
curl "http://localhost:8000/api/v1/batches?expiry_status=EXPIRING_SOON&location=fridge"
```

Search products:

```bash
curl "http://localhost:8000/api/v1/products?q=milk"
```

See all alerts:

```bash
curl "http://localhost:8000/api/v1/alerts"
```

See expired stock:

```bash
curl "http://localhost:8000/api/v1/alerts/expired"
```

See what expires in 7 days:

```bash
curl "http://localhost:8000/api/v1/alerts/expiring?within_days=7"
```

See the dashboard:

```bash
curl "http://localhost:8000/api/v1/dashboard/summary"
```

Look up a barcode:

```bash
curl "http://localhost:8000/api/v1/products/lookup/3017624010701"
```

Update one batch:

```bash
curl -X PATCH http://localhost:8000/api/v1/batches/1 -H "Content-Type: application/json" -d '{"quantity":4}'
```

Try to delete a product with stock, which returns 409:

```bash
curl -X DELETE http://localhost:8000/api/v1/products/1
```

Delete a batch:

```bash
curl -X DELETE http://localhost:8000/api/v1/batches/1
```

## External API: Open Food Facts

`GET /products/lookup/{barcode}` calls the
[Open Food Facts API](https://openfoodfacts.github.io/openfoodfacts-server/api/) v3.6, then returns
a normalized result:

```json
{"barcode": "3017624010701", "name": "Nutella", "brand": "Ferrero", "category": "Cocoa and hazelnuts spreads"}
```

To register a product by barcode, send that result to `POST /products`, editing it if needed. A
lookup saves nothing, and `POST /products` never calls the provider, so **manual registration keeps
working when the provider is down**.

- All provider-specific code is in `app/services/barcode_service.py`.
- The connection limit is 3 seconds, and the overall read limit is 5 seconds.
- Every provider field is treated as optional, so `name`, `brand`, and `category` can be `null`.
- The category is the most specific entry in `categories_tags_en` without a language prefix.
- The provider may pad the barcode, so `99999999999` can return as `0099999999999`.
- Provider error text goes to the server log and never reaches the client.

## Error handling

Every error uses one format:

```json
{"error": {"code": "product_not_found", "message": "Product 7 not found", "details": null}}
```

`details` lists the invalid fields on validation errors.

| Status | Code | Meaning |
|---|---|---|
| 401 | `invalid_api_key` | Missing or wrong API key |
| 404 | `product_not_found`, `batch_not_found`, `not_found` | The resource or route does not exist |
| 404 | `barcode_not_found` | Provider has no such product |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 409 | `duplicate_barcode` | Barcode already registered |
| 409 | `product_has_stock` | Product still has stock |
| 409 | `concurrent_modification` | Another request changed or deleted the record |
| 422 | `validation_error` | Invalid body, path, or query value |
| 422 | `invalid_barcode` | Provider rejected the barcode |
| 422 | `invalid_data` | PostgreSQL refused a value, such as a NUL byte |
| 500 | `internal_error` | Unexpected error; details are only in the server log |
| 502 | `provider_error` | Provider failed or sent an unusable response |
| 503 | `provider_rate_limited` | Provider returned 429 |
| 503 | `database_unavailable` | Database unreachable |
| 504 | `provider_timeout` | Provider did not respond in time |

## Deployment

**Public URL:** <https://expirywatch-duau.onrender.com>

| Page | URL |
|---|---|
| Swagger docs | <https://expirywatch-duau.onrender.com/docs> |
| ReDoc | <https://expirywatch-duau.onrender.com/redoc> |
| Health | <https://expirywatch-duau.onrender.com/health> |

It runs with `APP_ENV=production`, so protected routes need the deployment's API key. The free
service sleeps when idle, so the first request after a quiet period can take about a minute.

To deploy your own copy:

The repository includes a [Render Blueprint](render.yaml), which creates the web service and the
database. On Render:

1. Open the Dashboard, then select **New > Blueprint**.
2. Connect this repository, and choose the branch to deploy.
3. Review the resources, then select **Deploy Blueprint**.
4. Read the generated `APP_API_KEY` in the service's **Environment** tab.
5. Check `https://<your-service>.onrender.com/health` and `/docs`.

Migrations run when the container starts. The application reads Render's `PORT` variable.

## Known limitations

- **Render free tier:** the service sleeps after 15 minutes idle, and the next request takes about a
  minute. The free database expires after 30 days, and is deleted after a further 14-day grace
  period. It has no backups. Do not keep real data there.
- **Read routes are public.** Anyone with the URL can read inventory data. There are no user accounts
  or roles, and one API key covers all protected routes.
- **Quantities are whole numbers,** so 2.5 kg cannot be represented as a quantity.
- **Quantity updates set a value; they do not add to it.** If two clients update one batch at once,
  the last write wins.
- **Barcode padding is not normalized,** so `99999999999` and `0099999999999` count as different
  barcodes. Check digits are not validated.
- **Provider limits:** Open Food Facts allows 15 product reads per minute per IP. There are no retries
  or caching. The provider also signals exceeded global limits with 503, which cannot be told apart
  from downtime, so that case reports `provider_error`.
- **Migrations run on every start,** which is safe only with a single instance.
- **Alerts are API-only.** There is no email, SMS, or push notification.
- **Default timezone is UTC.** Set `APP_TIMEZONE`, or "today" changes at the wrong local hour.
- **Test warning:** Starlette warns that using `httpx` with its test client is deprecated. This
  affects tests only, and pinned versions keep working.
- **Deleting a product with expired stock is blocked** until its batches are deleted or set to 0.
