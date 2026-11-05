# Coding Agent Failure: Database Health Check That Reported Healthy Too Early

A real failure from building this project. The coding agent wrote the configuration below, and it
broke the core requirement that a new developer can clone the repository and run it.

Commit containing the fix: `fbf3ab2`.

## 1. Original proposal

The agent wrote this health check for the `db` service in `compose.yaml`, and made the API wait for
it with `depends_on: condition: service_healthy`:

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U expirywatch -d expirywatch"]
```

This looks correct, and it is the form commonly used for Postgres in Compose.

## 2. Why it was wrong

On first boot, with an empty volume, the official Postgres image runs in two stages:

1. It starts a **temporary server** to initialize the database. This server listens only on the Unix
   socket, not on TCP.
2. It shuts that server down and starts the **real server**, which listens on TCP.

`pg_isready` without `-h` connects over the Unix socket. So it reported success during stage 1, and
Compose marked the database healthy. The API then started and connected over TCP to a server that was
not listening yet.

The check answered "is a server answering on the socket?" when the API needed "can I connect the way
I actually will?"

## 3. How it was detected

By actually running the project from a clean copy of the tracked files, with a new volume, as a new
developer would:

```bash
cp .env.example .env
docker compose -p ewverify up --build -d --wait
```

Compose reported a failure, even though the database showed as healthy:

```text
container ewverify-api-1 exited (1)
db | Up 14 seconds (healthy)
sqlalchemy.exc.OperationalError: ... port 5432 failed: Connection refused
```

The container timestamps showed the order of events (all 2026-11-05, UTC):

| Time | Event |
|---|---|
| 17:51:41 | Temporary server starts, listening on the Unix socket only |
| 17:51:44 | API starts, and its migration fails with `Connection refused` |
| 17:51:48 | Real server listening on `0.0.0.0:5432` |

**Why it was missed earlier:** the failure appears only with an empty volume. The agent's local
development volume had already been initialized, so every earlier run passed. An earlier symptom was
also misread: in Phase 2 the check timed out on a slow first boot, and the agent raised
`start_period` without noticing that the check itself was testing the wrong thing.

## 4. Correction

Force the check over TCP. The temporary server has no TCP listener, so the check now passes only once
the real server is up:

```yaml
healthcheck:
  # -h forces TCP. During first boot a temporary init server answers on the Unix socket only,
  # so a socket check reports healthy too early and the API gets "connection refused".
  test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U expirywatch -d expirywatch"]
```

**Verified:** three fresh starts in a row, each deleting the volume first, all reached
`api=healthy db=healthy`.

## 5. Engineering lesson

- **A health check must test the path the client will really use.** Testing a nearby path proves
  something else.
- **"Works on my machine" can come from leftover state.** Only a clean environment tests the first-run
  experience, and that is the experience every new user gets.
- **Generated configuration needs running, not only reading.** This line looked right in review and
  would have passed any code reading. Only a real run exposed it.
- **Find the cause before changing a timeout.** Raising `start_period` hid the problem instead of
  explaining it.
