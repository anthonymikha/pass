import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import 'core/app_state.dart';
import 'core/router.dart';
import 'theme/tokens.dart';

class PassApp extends StatefulWidget {
  const PassApp({super.key, this.initialLocation = '/'});

  /// Tests start the app on a given path.
  final String initialLocation;

  @override
  State<PassApp> createState() => _PassAppState();
}

class _PassAppState extends State<PassApp> {
  final AppState state = AppState.instance;
  late final GoRouter router = buildRouter(state, initialLocation: widget.initialLocation);

  // FE-8: coming back to the app refreshes the coach badge.
  late final AppLifecycleListener _life = AppLifecycleListener(onResume: state.refresh);

  @override
  void dispose() {
    _life.dispose();
    router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: state,
        builder: (context, _) {
          // The app follows the device's light or dark appearance.
          final brightness = MediaQuery.platformBrightnessOf(context);
          final c = brightness == Brightness.dark ? PassColors.dark : PassColors.light;
          return CupertinoApp.router(
            title: 'PASS',
            debugShowCheckedModeBanner: false,
            routerConfig: router,
            theme: CupertinoThemeData(
              brightness: brightness,
              primaryColor: c.tint,
              scaffoldBackgroundColor: c.bgGrouped,
              barBackgroundColor: c.bgGrouped,
              textTheme: CupertinoTextThemeData(
                primaryColor: c.tint,
                textStyle: PassText.body.copyWith(color: c.label),
              ),
            ),
            builder: (context, child) => DefaultTextStyle(
              style: PassText.body.copyWith(color: c.label),
              child: child ?? const SizedBox.shrink(),
            ),
          );
        },
      );
}
