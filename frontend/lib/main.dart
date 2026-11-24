import 'package:flutter/material.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:go_router/go_router.dart';

import 'api.dart';
import 'push.dart';
import 'screens/auth.dart';
import 'screens/club.dart';
import 'screens/player.dart';
import 'screens/profile.dart';
import 'screens/sessions.dart';

final messenger = GlobalKey<ScaffoldMessengerState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  usePathUrlStrategy(); // web URLs without '#'
  await Api.instance.load();
  final router = buildRouter();
  Api.instance.onSignedIn = () => setupPush(router, messenger);
  runApp(PassApp(router: router));
  setupPush(router, messenger);
}

GoRouter buildRouter() {
  GoRoute id(String path, Widget Function(int id) page, {List<RouteBase> routes = const []}) => GoRoute(
        path: path,
        builder: (_, s) => page(int.parse(s.pathParameters['id']!)),
        routes: routes,
      );
  return GoRouter(
    initialLocation: '/courts',
    refreshListenable: Api.instance,
    redirect: (context, state) {
      final open = const ['/login', '/register', '/forgot'].contains(state.matchedLocation);
      if (!Api.instance.signedIn) return open ? null : '/login';
      return open ? '/courts' : null;
    },
    routes: [
      for (final mode in ['login', 'register', 'forgot']) GoRoute(path: '/$mode', builder: (_, _) => AuthScreen(mode: mode)),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => Shell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: '/courts', builder: (_, _) => const CourtsScreen(), routes: [id(':id', (i) => CourtScreen(id: i))]),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/coaches', builder: (_, _) => const CoachesScreen(), routes: [id(':id', (i) => CoachScreen(id: i))]),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/sessions', builder: (_, _) => const SessionsScreen(), routes: [
              id(':id', (i) => SessionScreen(id: i), routes: [
                GoRoute(path: 'confirm', builder: (_, s) => ConfirmScreen(id: int.parse(s.pathParameters['id']!))),
              ]),
            ]),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/clubs', builder: (_, _) => const ClubsScreen(), routes: [
              id(':id', (i) => ClubScreen(id: i), routes: [
                GoRoute(
                    path: 'courts/:court/prices',
                    builder: (_, s) => PricesScreen(court: int.parse(s.pathParameters['court']!))),
              ]),
            ]),
          ]),
          StatefulShellBranch(routes: [GoRoute(path: '/profile', builder: (_, _) => const ProfileScreen())]),
        ],
      ),
    ],
  );
}

class PassApp extends StatelessWidget {
  const PassApp({super.key, required this.router});
  final GoRouter router;

  static const brand = Color(0xFF1E8E3E); // FE-10: one green

  ThemeData _theme(Brightness b) => ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: brand, brightness: b),
        inputDecorationTheme: const InputDecorationTheme(isDense: true),
      );

  @override
  Widget build(BuildContext context) => MaterialApp.router(
        title: 'PASS',
        debugShowCheckedModeBanner: false,
        scaffoldMessengerKey: messenger,
        theme: _theme(Brightness.light),
        darkTheme: _theme(Brightness.dark),
        routerConfig: router,
      );
}

/// FE-2: one app, layout by width. A bottom bar on phones, a side rail on wide screens.
class Shell extends StatelessWidget {
  const Shell({super.key, required this.shell});
  final StatefulNavigationShell shell;

  static const _items = [
    (Icons.sports_tennis, 'Courts'),
    (Icons.sports, 'Coaches'),
    (Icons.event, 'Sessions'),
    (Icons.store, 'My clubs'),
    (Icons.person, 'Profile'),
  ];

  void _go(int i) => shell.goBranch(i, initialLocation: i == shell.currentIndex);

  @override
  Widget build(BuildContext context) {
    if (MediaQuery.sizeOf(context).width >= 800) {
      return Scaffold(
        body: Row(children: [
          NavigationRail(
            selectedIndex: shell.currentIndex,
            onDestinationSelected: _go,
            labelType: NavigationRailLabelType.all,
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Text('PASS',
                  style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 2, color: Theme.of(context).colorScheme.primary)),
            ),
            destinations: [for (final (icon, label) in _items) NavigationRailDestination(icon: Icon(icon), label: Text(label))],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: shell),
        ]),
      );
    }
    return Scaffold(
      body: shell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: shell.currentIndex,
        onDestinationSelected: _go,
        destinations: [for (final (icon, label) in _items) NavigationDestination(icon: Icon(icon), label: label)],
      ),
    );
  }
}
