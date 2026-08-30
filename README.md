# Mentora

Mentora is a persistent AI whiteboard tutor. A student works by hand on a
tldraw canvas, then asks for Mark, Hint, Explain, or I'm Stuck. The backend
sends the canvas to a multimodal Gemini agent and returns validated spatial
actions for the whiteboard renderer to draw.

## Repository

- `frontend/`: Next.js, React, and tldraw whiteboard UI.
- `backend/`: FastAPI tutor service and course ingestion.
- `docs/PRODUCT.md`: authoritative product behavior.
- `docs/ARCHITECTURE.md`: system boundaries and shared contracts.
- `docs/TUTOR_AGENT.md`: the tutor API contract.

## Run with Docker

The whole stack, one command. Needs Docker Desktop and nothing else — no
Python, no Bun, no local installs.

**On Windows, install WSL2 first.** Docker Desktop alone is not enough. A
container is a process the *Linux* kernel isolates, not a virtual machine, so
a Linux image needs a Linux kernel to run on — and WSL2 is what supplies one
on Windows. Without it Docker Desktop starts but its engine does not, and
every command fails with a 500 from the daemon. In an **Administrator**
PowerShell:

```powershell
wsl --install --no-distribution
```

Then restart the machine (a full Restart, not Shut down — Fast Startup can
skip pending component changes) and launch Docker Desktop, which is ready when
the whale icon reads "Engine running". `--no-distribution` skips Ubuntu, about
1 GB nobody here needs: Docker Desktop ships its own `docker-desktop` distro.
Budget ~1.5 GB for WSL2 and ~8 GB once the images are built.

Windows 11 Home has no other option — Docker Desktop's old Hyper-V backend is
deprecated, and Hyper-V is a Pro/Enterprise feature. WSL2 works on Home
because it uses Virtual Machine Platform, a smaller component Home does ship.

macOS and Linux need nothing extra: Docker Desktop supplies its own Linux VM
on macOS, and on Linux the host kernel already is one.

```bash
cp backend/.env.example backend/.env   # then paste a real GEMINI_API_KEY into it
docker compose up
```

Then open `localhost:3000`. The API is on `localhost:8000`; check it came up
configured with `curl -s localhost:8000/health`.

Source is bind-mounted, so both servers reload on edit — this is the
development setup, not a production image. Stop with Ctrl-C, or `docker
compose down`. After changing `requirements.txt` or `package.json`, rebuild:
`docker compose up --build`.

Leave `NEXT_PUBLIC_API_BASE_URL` unset. The frontend calls the backend from
your browser, not from inside the container, so it needs `localhost:8000` —
the published port — and the code already defaults there. Pointing it at
`http://backend:8000` breaks the app: that name only resolves on Compose's
internal network.

To reach it from a phone or tablet on the same network, set both origins on
the host before `docker compose up`:

```bash
CORS_ALLOW_ORIGINS=http://localhost:3000,http://YOUR-IP:3000 \
  ALLOWED_DEV_ORIGINS=YOUR-IP docker compose up
```

The same warning as below applies: published ports reach your whole network,
there is no authentication, and every request spends Gemini quota.

### Platform notes

The setup runs on macOS, Linux, and Windows from the same two files. Nothing
pins an architecture, and both base images are multi-arch, so an Apple Silicon
Mac builds arm64 natively. If a build fails, do not reach for
`platform: linux/amd64` — that forces every container through emulation and
hides the real error.

Needs Docker Compose v2.24+ (`docker compose version`). Docker Desktop ships
newer; a Linux box on a distro-packaged plugin may not.

**Edits not reloading?** On macOS and Windows the containers run in a Linux VM,
and filesystem events do not always cross the bind mount into it. Turn on
polling — it costs constant CPU, which is why it is off by default, and why
native Linux does not need it:

```bash
WATCHFILES_FORCE_POLLING=true WATCHPACK_POLLING=true docker compose up
```

**After changing `package.json` or `requirements.txt`**, rebuild *and* refresh
the anonymous volumes — `node_modules` survives a plain `--build`, so a new
dependency appears installed but is not there:

```bash
docker compose up --build --renew-anon-volumes
```

**On Linux**, bind mounts pass your host UID straight through instead of
mapping it as Docker Desktop does, and both containers run as root. Anything a
container creates in `backend/` or `frontend/` is therefore root-owned on the
host. Little is written there — `node_modules` and `.next` live in volumes, and
`PYTHONDONTWRITEBYTECODE` suppresses `__pycache__` — but `backend/mentora.db`
is one to watch. `sudo chown -R "$USER" backend frontend` if it happens.

Line endings are pinned to LF for `Dockerfile`, `.dockerignore`, and the
compose file in `.gitattributes`. They are read inside a Linux container, where
a trailing CR becomes part of the value: a CRLF `.dockerignore` matches
nothing, silently shipping `node_modules/` and `.venv/` into the build context.

The rest of this section is the manual setup, for working without Docker.

## Setup on a new machine

Four things are gitignored and must be recreated: `backend/.venv`,
`backend/.env`, `frontend/.env.local`, and `frontend/node_modules`.

### Backend

Needs Python 3.11 or newer (`asyncio.timeout`).

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then paste a real GEMINI_API_KEY into it
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Only `GEMINI_API_KEY` is required. The OpenAI and Pinecone keys in
`.env.example` are for course ingestion, which the tutor does not use — see
"Deferred" in `docs/TUTOR_AGENT.md`.

Check it came up configured:

```bash
curl -s localhost:8000/health     # {"status":"ok","tutor":"ready","missing_settings":[]}
```

### Frontend

```bash
cd frontend
bun install
cp .env.example .env.local        # already points at localhost:8000
bun dev
```

Then open `localhost:3000` → My courses → a course → New space → draw → tap a
tutor button.

### From a phone or tablet on the same network

The frontend points itself at whatever host served the page, so the API base
URL needs no configuration. Two things do: the backend must accept that origin
and listen beyond loopback, and Next must allow the origin to reach its dev
server.

```bash
# backend, in place of the command above
CORS_ALLOW_ORIGINS=http://localhost:3000,http://YOUR-IP:3000 \
  .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend
ALLOWED_DEV_ORIGINS=YOUR-IP bun dev --hostname 0.0.0.0
```

`ALLOWED_DEV_ORIGINS` is a comma-separated list of hostnames; without it Next
blocks the tablet's cross-origin requests for dev-only assets. It can live in
`frontend/.env.local` instead of the command line.

`--host 0.0.0.0` exposes the API to your whole network, and on a machine with
a public address, to the internet. There is no authentication and every
request spends Gemini quota, so only do this on a trusted network and stop the
server afterwards.

## The tutor endpoint

`POST /api/tutor/analyze`, multipart form data:

```text
course_id          retrieval scope (carried; retrieval is deferred)
mode               mark | hint | explain | stuck
canvas_image       PNG, JPEG, or WebP; maximum 10 MB
prior_annotations  JSON array of normalized bounds; defaults to []
```

Full contract in `docs/TUTOR_AGENT.md`.

## Tests

```bash
cd backend  && .venv/bin/python -m pytest -q -m "not live"    # 101, no provider calls
cd frontend && bun run test                                    # 166
```

The opt-in live check spends one real Gemini request:

```bash
cd backend && RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest -q -m live -s
```

Korey's credentialed RAG pipeline check needs the OpenAI and Pinecone keys:

```bash
cd backend && .venv/bin/python test_pipeline.py
```

## Team workstreams

- Jaden: whiteboard and frontend integration.
- Andre: AI/Vision and backend tutor APIs.
- Korey: course context ingestion and retrieval.
- Ren: question generation and learning engine (`ren/learning-engine`, not yet
  integrated — see "Deferred" in `docs/TUTOR_AGENT.md`).
