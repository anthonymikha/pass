// All routes of the app (path-based URLs, FE-10).
import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/auth_screens.dart';
import '../features/book/book_screens.dart';
import '../features/club/club_screens.dart';
import '../features/profile/profile_screens.dart';
import '../features/sessions/sessions_screens.dart';
import '../widgets/app_shell.dart';
import 'app_state.dart';

const _publicPaths = {'/welcome', '/signin', '/signup', '/forgot'};

bool _under(String path, String root) => path == root || path.startsWith('$root/');

/// Auth guard; the Club tab is the club side's only (FE-11).
String? guard(AppState s, String path) {
  if (!s.signedIn) return _publicPaths.contains(path) ? null : '/welcome';
  if (path == '/' || _publicPaths.contains(path)) return '/book';
  if (_under(path, '/club') && s.clubSide.isEmpty) return '/book';
  return null;
}

int _id(GoRouterState st, [String name = 'id']) => int.tryParse(st.pathParameters[name] ?? '') ?? 0;

Page<void> _push(GoRouterState st, Widget child) => CupertinoPage(key: st.pageKey, child: child);

/// Tab roots: quick crossfade (pushes use the iOS slide with swipe-back).
Page<void> _root(GoRouterState st, Widget child) => CustomTransitionPage(
      key: st.pageKey,
      child: child,
      transitionDuration: const Duration(milliseconds: 180),
      reverseTransitionDuration: const Duration(milliseconds: 120),
      transitionsBuilder: (context, animation, _, child) =>
          FadeTransition(opacity: CurvedAnimation(parent: animation, curve: Curves.easeOut), child: child),
    );

GoRouter buildRouter(AppState state, {String initialLocation = '/'}) => GoRouter(
      initialLocation: initialLocation,
      refreshListenable: state,
      redirect: (context, st) => guard(state, st.uri.path),
      routes: [
        GoRoute(path: '/', redirect: (_, __) => '/book'),
        GoRoute(path: '/welcome', pageBuilder: (c, st) => _root(st, const WelcomeScreen())),
        GoRoute(path: '/signin', pageBuilder: (c, st) => _push(st, const SignInScreen())),
        GoRoute(path: '/signup', pageBuilder: (c, st) => _push(st, const SignUpScreen())),
        GoRoute(path: '/forgot', pageBuilder: (c, st) => _push(st, const ForgotPasswordScreen())),
        // Each tab is a branch with its own navigator, kept alive like iOS tabs.
        // Branch order = shellBranchRoots in app_shell.dart.
        StatefulShellRoute.indexedStack(
          builder: (context, st, shell) => AppShell(shell: shell),
          branches: [
            StatefulShellBranch(routes: [
              GoRoute(path: '/book', pageBuilder: (c, st) => _root(st, const BookScreen()), routes: [
                GoRoute(path: 'clubs/:id', pageBuilder: (c, st) => _push(st, ClubScreen(id: _id(st)))),
                GoRoute(path: 'courts/:id', pageBuilder: (c, st) => _push(st, CourtScreen(id: _id(st)))),
                GoRoute(path: 'coaches/:id', pageBuilder: (c, st) => _push(st, CoachScreen(id: _id(st)))),
              ]),
            ]),
            StatefulShellBranch(routes: [
              GoRoute(path: '/sessions', pageBuilder: (c, st) => _root(st, const SessionsScreen()), routes: [
                GoRoute(path: ':id', pageBuilder: (c, st) => _push(st, SessionDetailScreen(id: _id(st))), routes: [
                  GoRoute(path: 'confirm', pageBuilder: (c, st) => _push(st, ConfirmTrainingScreen(id: _id(st)))),
                ]),
              ]),
            ]),
            StatefulShellBranch(routes: [
              GoRoute(path: '/club', pageBuilder: (c, st) => _root(st, const MyClubsScreen()), routes: [
                GoRoute(path: ':id', pageBuilder: (c, st) => _push(st, ClubScheduleScreen(id: _id(st))), routes: [
                  GoRoute(path: 'setup', pageBuilder: (c, st) => _push(st, ClubSetupScreen(id: _id(st)))),
                  GoRoute(path: 'courts/new', pageBuilder: (c, st) => _push(st, CourtEditScreen(clubId: _id(st)))),
                  GoRoute(
                      path: 'courts/:court',
                      pageBuilder: (c, st) => _push(st, CourtEditScreen(clubId: _id(st), courtId: _id(st, 'court')))),
                  GoRoute(path: 'equipment', pageBuilder: (c, st) => _push(st, EquipmentScreen(clubId: _id(st)))),
                  GoRoute(path: 'staff', pageBuilder: (c, st) => _push(st, StaffScreen(clubId: _id(st)))),
                ]),
              ]),
            ]),
            StatefulShellBranch(routes: [
              GoRoute(path: '/profile', pageBuilder: (c, st) => _root(st, const ProfileScreen()), routes: [
                GoRoute(path: 'new-club', pageBuilder: (c, st) => _push(st, const NewClubScreen())),
                GoRoute(path: 'delete', pageBuilder: (c, st) => _push(st, const DeleteAccountScreen())),
              ]),
            ]),
          ],
        ),
      ],
    );
