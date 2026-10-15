FROM rust@sha256:114c7a4425406451c2866b6aafe69fe29b1b298832db1277d411ac73c82d04d6
ENV RADHOUSE_NATIVE_PAGE_ONLY=1 CARGO_TARGET_DIR=/build-target
WORKDIR /build
COPY source /build
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/usr/local/cargo/git --mount=type=cache,target=/build-target \
    cargo test --locked --profile ci --jobs 2 --target x86_64-unknown-linux-gnu --manifest-path cli/Cargo.toml radhouse_ -- --test-threads=1 && \
    cargo test --locked --profile ci --jobs 2 --target x86_64-unknown-linux-gnu --manifest-path cli/Cargo.toml native::stream -- --test-threads=1 && \
    cargo test --locked --profile ci --jobs 2 --target x86_64-unknown-linux-gnu --manifest-path cli/Cargo.toml native::browser::tests -- --test-threads=1 && \
    cargo test --locked --profile ci --jobs 2 --target x86_64-unknown-linux-gnu --manifest-path cli/Cargo.toml flags::tests -- --test-threads=1 && \
    cargo build --locked --profile ci --jobs 2 --target x86_64-unknown-linux-gnu --manifest-path cli/Cargo.toml && \
    cp /build-target/x86_64-unknown-linux-gnu/ci/agent-browser /opt/page-only-agent-browser
