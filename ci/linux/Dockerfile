# Linux check for OpenHarnX with the srt sandbox (T79 slice 2).
# Build: docker build -t ohx-linux ci/linux
# Run:   docker run --rm --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
#          --security-opt systempaths=unconfined --tmpfs /home/ci:rw,exec,size=2g,uid=1000 \
#          -v "$PWD":/src:ro ohx-linux /src/ci/linux/check.sh
# bubblewrap needs user namespaces, which Docker's default seccomp profile blocks, and must
# mount /proc, which Docker masks. A CI virtual machine needs neither option.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap socat ripgrep git zsh openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/sandbox-runtime@0.0.77 \
    && pip install --no-cache-dir uv
# srt advises a non-root caller.
RUN useradd -m ci
USER ci
WORKDIR /home/ci
