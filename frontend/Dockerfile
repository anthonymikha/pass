# The Flutter web build served by Caddy, which also forwards Django's paths: one origin, no CORS (FE spec, "Build").
# Same Flutter version as the tests and the phone builds (.github/workflows/mobile.yml).
FROM ghcr.io/cirruslabs/flutter:3.35.7 AS build
WORKDIR /app
COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get
COPY . .
RUN flutter build web --release

FROM caddy:2.10
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/build/web /srv
