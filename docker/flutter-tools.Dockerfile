# Local Flutter toolchain image used by scripts/flutter.sh (dev only).
# Same pinned SDK as the production build stage, with web artifacts pre-cached.
FROM ghcr.io/cirruslabs/flutter:3.35.7
RUN flutter config --no-analytics --enable-web >/dev/null \
 && flutter precache --web \
 && git config --system --add safe.directory '*'
