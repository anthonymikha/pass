// In-app shell. Phone: floating glass tab bar over the screen. Desktop: left sidebar.
import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../core/app_state.dart';
import '../theme/tokens.dart';
import 'controls.dart';
import 'svg_icon.dart';

class TabItem {
  const TabItem(this.label, this.path, this.icon);
  final String label, path;

  /// Null: the user's initials (Profile).
  final String? icon;
}

/// FE-10: one account, no role choice. Club shows only to the club side (FE-11).
List<TabItem> tabsFor(AppState s) => [
      const TabItem('Book', '/book', PassIcons.play),
      const TabItem('Sessions', '/sessions', PassIcons.schedule),
      if (s.clubSide.isNotEmpty) const TabItem('Club', '/club', PassIcons.home),
      const TabItem('Profile', '/profile', null),
    ];

/// Root path of each shell branch, in the router's branch order.
const shellBranchRoots = ['/book', '/sessions', '/club', '/profile'];

/// iOS tab behaviour: tapping a tab shows it as you left it; tapping the active tab goes back to its root.
/// FE-8: showing a tab again refreshes the coach badge (and the Club tab).
void goTab(BuildContext context, String root) {
  AppState.instance.refresh();
  final shell = StatefulNavigationShell.maybeOf(context);
  final i = shellBranchRoots.indexOf(root);
  if (shell == null || i < 0) return context.go(root);
  shell.goBranch(i, initialLocation: i == shell.currentIndex);
}

/// Sessions tab badge (FE-8): training requests waiting for this coach.
Widget? _badge(BuildContext context, TabItem t) {
  final n = AppState.instance.requestCount;
  if (t.path != '/sessions' || n == 0) return null;
  final c = context.c;
  return Container(
    constraints: const BoxConstraints(minWidth: 18),
    padding: const EdgeInsets.symmetric(horizontal: PassSpace.xs, vertical: 1),
    decoration: BoxDecoration(color: c.tint, borderRadius: BorderRadius.circular(PassRadii.pill)),
    child: Text('$n',
        textAlign: TextAlign.center, style: PassText.caption2.copyWith(color: PassColors.white, fontWeight: PassText.bold)),
  );
}

Widget _icon(BuildContext context, TabItem t, Color color, double size) {
  if (t.icon != null) return SvgIcon(t.icon!, color: color, width: size + 4, height: size, evenOdd: true);
  final c = context.c;
  return Avatar(AppState.instance.me?.initials ?? '', size: size, bg: color == c.tint ? c.tint : c.fill2,
      fg: color == c.tint ? PassColors.white : c.label, fontSize: size * .45);
}

class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.shell});
  final StatefulNavigationShell shell;

  // The tabs (Club) and the badge follow the app state (FE-8, FE-11).
  @override
  Widget build(BuildContext context) => ListenableBuilder(listenable: AppState.instance, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final Widget child = shell;
    final state = AppState.instance;
    final path = GoRouterState.of(context).uri.path;
    final tabs = tabsFor(state);
    final c = context.c;
    if (context.isDesktop) {
      return ColoredBox(
        color: c.bgGrouped,
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _Sidebar(tabs: tabs, path: path),
          // Own semantics container: a route's modal barrier would otherwise hide the sidebar from screen readers.
          Expanded(child: Semantics(container: true, child: child)),
        ]),
      );
    }
    // Like iOS hidesBottomBarWhenPushed: the bar slides away inside a chat and while the keyboard is up.
    final hidden = hidesTabBar(path) || MediaQuery.viewInsetsOf(context).bottom > 0;
    return ColoredBox(
      color: c.bgGrouped,
      child: Stack(children: [
        Positioned.fill(child: child),
        Positioned(
          left: 12,
          right: 12,
          bottom: PassSpace.tabBarBottom + MediaQuery.paddingOf(context).bottom * .5,
          child: IgnorePointer(
            ignoring: hidden,
            child: AnimatedSlide(
              offset: hidden ? const Offset(0, 1.6) : Offset.zero,
              duration: PassMotion.smooth.duration,
              curve: PassMotion.smooth,
              child: AnimatedOpacity(
                opacity: hidden ? 0 : 1,
                duration: PassMotion.normal,
                child: _TabBar(tabs: tabs, path: path),
              ),
            ),
          ),
        ),
      ]),
    );
  }
}

/// Screens that cover the phone tab bar (none in the MVP; pass_v1 used it for a chat thread).
bool hidesTabBar(String path) => false;

bool _isActive(String path, String tabPath) => path == tabPath || path.startsWith('$tabPath/');

class _TabBar extends StatelessWidget {
  const _TabBar({required this.tabs, required this.path});
  final List<TabItem> tabs;
  final String path;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final active = tabs.indexWhere((t) => _isActive(path, t.path));
    final n = tabs.length;
    return SizedBox(
      height: PassSpace.tabBarHeight,
      child: Glass(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Stack(alignment: Alignment.center, children: [
          // Selection pill slides between tabs (iOS 26 tab bar).
          Positioned.fill(
            child: AnimatedOpacity(
              opacity: active < 0 ? 0 : 1,
              duration: PassMotion.fast,
              child: AnimatedAlign(
                alignment: Alignment(active < 0 ? 0 : -1 + 2 * active / (n - 1), 0),
                duration: PassMotion.snappy.duration,
                curve: PassMotion.snappy,
                child: FractionallySizedBox(
                  widthFactor: 1 / n,
                  child: Container(
                    height: 56,
                    decoration: BoxDecoration(color: c.tabSel, borderRadius: BorderRadius.circular(PassRadii.pill)),
                  ),
                ),
              ),
            ),
          ),
          Row(children: [
            for (var i = 0; i < n; i++)
              Expanded(
                child: Pressable(
                  onTap: () => goTab(context, tabs[i].path),
                  child: SizedBox(
                    height: 56,
                    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                      // Icon pops when its tab becomes active.
                      TweenAnimationBuilder<double>(
                        key: ValueKey(i == active),
                        tween: Tween(begin: i == active ? .78 : 1, end: 1),
                        duration: PassMotion.bouncy.duration,
                        curve: PassMotion.bouncy,
                        builder: (context, s, child) => Transform.scale(scale: s, child: child),
                        child: Stack(clipBehavior: Clip.none, children: [
                          _icon(context, tabs[i], i == active ? c.tint : c.label, 24),
                          if (_badge(context, tabs[i]) case final b?) Positioned(top: -4, right: -12, child: b),
                        ]),
                      ),
                      const SizedBox(height: 2),
                      AnimatedDefaultTextStyle(
                        duration: PassMotion.fast,
                        style: PassText.tabLabel.copyWith(color: i == active ? c.tint : c.label),
                        child: Text(tabs[i].label),
                      ),
                    ]),
                  ),
                ),
              ),
          ]),
        ]),
      ),
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.tabs, required this.path});
  final List<TabItem> tabs;
  final String path;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final state = AppState.instance;
    Widget item(String label, String target, Widget icon, {Widget? badge}) {
      final active = _isActive(path, target);
      return Pressable(
        onTap: () => goTab(context, target),
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: PassSpace.ml, vertical: 2),
          padding: const EdgeInsets.symmetric(horizontal: PassSpace.ml, vertical: PassSpace.m),
          decoration: BoxDecoration(
            color: active ? c.tabSel : PassColors.transparent,
            borderRadius: BorderRadius.circular(PassRadii.slot),
          ),
          child: Row(children: [
            icon,
            const SizedBox(width: PassSpace.ml),
            Expanded(
              child: Text(label,
                  style: PassText.body.copyWith(
                      color: active ? c.tint : c.label, fontWeight: active ? PassText.semibold : PassText.regular)),
            ),
            ?badge,
          ]),
        ),
      );
    }

    return Container(
      width: PassSpace.sidebarWidth,
      decoration: BoxDecoration(color: c.bgCard, border: Border(right: BorderSide(color: c.sep, width: PassSpace.hairline))),
      child: SafeArea(
        right: false,
        child: ListenableBuilder(
          listenable: state,
          builder: (context, _) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(PassSpace.xxl, PassSpace.xxl, PassSpace.xxl, PassSpace.gutter),
              child: Text('PASS', style: PassText.wordmark.copyWith(fontSize: 34, color: c.tint)),
            ),
            for (final t in tabs.where((t) => t.icon != null))
              item(t.label, t.path, _icon(context, t, _isActive(path, t.path) ? c.tint : c.label, 22),
                  badge: _badge(context, t)),
            const Spacer(),
            if (state.me != null)
              item(state.me!.fullName, '/profile',
                  Avatar(state.me!.initials, size: 28, bg: c.tint, fg: PassColors.white, fontSize: 12)),
            const SizedBox(height: PassSpace.ml),
          ]),
        ),
      ),
    );
  }
}
