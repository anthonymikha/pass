{{flutter_js}}
{{flutter_build_config}}

// Everything is served from this origin: CanvasKit and fallback fonts are
// bundled locally (built with --no-web-resources-cdn). No service worker is
// registered, so API calls are never cached and new deploys show immediately.
_flutter.loader.load({
  config: {
    canvasKitBaseUrl: "canvaskit/",
    fontFallbackBaseUrl: "assets/fallback-fonts/",
  },
});
