# Mentora whiteboard UI. Bun matches the team's workflow and bun.lock.
#
# No `platform:` is pinned anywhere: this image and python:3.12-slim are both
# multi-arch, so an Apple Silicon Mac builds arm64 natively. Forcing
# linux/amd64 would drag every container through emulation.
FROM oven/bun:1

# The base image ends on `USER bun`, and COPY writes as root regardless of the
# active user — so `bun install` into a root-owned /app fails with EACCES.
# Staying root also keeps bind-mounted writes working on Linux, where the host
# UID is passed straight through rather than mapped as it is on Docker Desktop.
# This is a development image; a production one should drop back to `bun`.
USER root

WORKDIR /app

# Copied before the source so a code edit does not reinstall dependencies.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

EXPOSE 3000

# --hostname 0.0.0.0 binds beyond the container's loopback so the published
# port reaches the host; without it Next answers only inside the container.
CMD ["bun", "run", "dev", "--hostname", "0.0.0.0", "--port", "3000"]
