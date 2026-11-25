// Loads data from the API and shows a spinner, an error with retry, or the content.
import 'package:flutter/cupertino.dart';

import '../core/api_client.dart';
import '../theme/tokens.dart';
import 'controls.dart';
import 'scaffold.dart';

/// Usage:
/// ```dart
///   ApiLoader<Map<String, dynamic>>(
///     load: () async => await api.get('/api/home/') as Map<String, dynamic>,
///     builder: (context, data, reload) => ...,
///   )
/// ```
/// Keep a `GlobalKey<ApiLoaderState>` to call reload() from outside (e.g. after a mutation).

/// For screens kept alive in a tab: when the tab is shown again, [refreshOnReturn] runs if something was
/// changed since the last load (any write) or the data is older than [ApiClient.cacheTtl]. The old data stays
/// on screen meanwhile (iOS refresh-on-appear). Call [markLoaded] after each successful load.
mixin RefreshOnReturn<W extends StatefulWidget> on State<W> {
  bool _shown = true;
  int _writes = ApiClient.instance.writes;
  DateTime _loadedAt = DateTime.now();

  void markLoaded() {
    _writes = ApiClient.instance.writes;
    _loadedAt = DateTime.now();
  }

  Future<void> refreshOnReturn();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final shown = TickerMode.of(context); // false while the tab is in the background
    if (shown &&
        !_shown &&
        (ApiClient.instance.writes != _writes || DateTime.now().difference(_loadedAt) > ApiClient.cacheTtl)) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) refreshOnReturn();
      });
    }
    _shown = shown;
  }
}
class ApiLoader<T> extends StatefulWidget {
  const ApiLoader({super.key, required this.load, required this.builder, this.loading, this.version, this.back});
  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;
  final Widget? loading;

  /// A change reloads in place: the old data stays on screen until the new data comes (after a save, a new search).
  /// A new [key] instead starts over with the spinner.
  final Object? version;

  /// Set when the loader is a whole screen: while loading, and on an error, it keeps a nav bar with Back to this path
  /// (an installed web app has no browser Back).
  final String? back;

  @override
  State<ApiLoader<T>> createState() => ApiLoaderState<T>();
}

class ApiLoaderState<T> extends State<ApiLoader<T>> with RefreshOnReturn {
  T? _data;
  Object? _error;
  bool _loading = true;
  final _born = DateTime.now();

  /// Data came (from the API client's cache) right away: show it without the fade.
  bool _instant = false;

  /// Only the latest fetch may land: an older one can answer after a newer one (fast typing in a search).
  int _gen = 0;

  @override
  void initState() {
    super.initState();
    _fetch(fresh: false); // first load may come from the cache
  }

  @override
  void didUpdateWidget(covariant ApiLoader<T> oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.version != widget.version) reload();
  }

  /// Re-fetches from the server; keeps showing the old data while loading.
  Future<void> reload() => _fetch(fresh: true);

  @override
  Future<void> refreshOnReturn() => reload();

  Future<void> _fetch({required bool fresh}) async {
    final gen = ++_gen;
    setState(() => _loading = _data == null);
    try {
      final d = await (fresh ? ApiClient.fresh(widget.load) : widget.load());
      if (mounted && gen == _gen) {
        setState(() {
          if (_data == null && DateTime.now().difference(_born) < const Duration(milliseconds: 120)) _instant = true;
          _data = d;
          markLoaded();
          _error = null;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted && gen == _gen) {
        setState(() {
          _error = e;
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final Widget child;
    Widget screen(Widget view) => widget.back == null ? view : PassScaffold(title: '', back: widget.back, children: [view]);
    if (_data != null) {
      child = KeyedSubtree(key: const ValueKey('data'), child: widget.builder(context, _data as T, reload));
    } else if (_loading) {
      child = KeyedSubtree(key: const ValueKey('loading'), child: screen(widget.loading ?? const LoadingView()));
    } else {
      child = KeyedSubtree(key: const ValueKey('error'), child: screen(ErrorView(error: _error, onRetry: reload)));
    }
    // Content fades in over the spinner; reloads keep the 'data' key, so they don't animate.
    return AnimatedSwitcher(
      duration: _instant ? Duration.zero : PassMotion.normal,
      switchInCurve: Curves.easeOut,
      layoutBuilder: (current, previous) => Stack(
        fit: StackFit.passthrough,
        alignment: Alignment.topCenter,
        children: [...previous, if (current != null) current],
      ),
      child: child,
    );
  }
}

class LoadingView extends StatelessWidget {
  const LoadingView({super.key});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(48),
        // Spinner appears only if loading takes longer than ~150 ms (fast loads show no flash).
        child: Center(
          child: TweenAnimationBuilder<double>(
            tween: Tween(begin: 0, end: 1),
            duration: const Duration(milliseconds: 300),
            curve: const Interval(.5, 1),
            builder: (context, v, child) => Opacity(opacity: v, child: child),
            child: const CupertinoActivityIndicator(radius: 12),
          ),
        ),
      );
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.error, required this.onRetry});
  final Object? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(PassSpace.xxxl),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('$error', textAlign: TextAlign.center, style: PassText.subhead.copyWith(color: context.c.label2)),
          const SizedBox(height: PassSpace.ml),
          PassLink('Try again', onTap: onRetry),
        ]),
      );
}

/// Centred empty-state text inside a card area.
class EmptyText extends StatelessWidget {
  const EmptyText(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: PassSpace.lg),
        child: Text(text, textAlign: TextAlign.center, style: PassText.subhead.copyWith(color: context.c.label2)),
      );
}
