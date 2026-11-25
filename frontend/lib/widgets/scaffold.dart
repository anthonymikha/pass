// Screen scaffold: iOS-style nav bar (glass buttons, title fades in on scroll) + scrolling content.
// Every in-app screen builds a PassScaffold. Bottom tab bar / desktop sidebar come from AppShell.
import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../core/app_state.dart';
import '../theme/tokens.dart';
import 'app_shell.dart' show hidesTabBar;
import 'controls.dart';
import 'svg_icon.dart';

class PassScaffold extends StatefulWidget {
  const PassScaffold({
    super.key,
    required this.title,
    this.children = const [],
    this.subtitle,
    this.body,
    this.back,
    this.onBack,
    this.onRefresh,
    this.bottom,
    this.maxWidth = 760,
    this.alwaysShowTitle = false,
    this.trailing,
  });

  /// Nav bar title; hidden until content scrolls past 40px (iOS large-title behaviour).
  final String title;

  /// Second nav-bar line under the title (chat subtitle); shown with the title.
  final String? subtitle;

  /// Scrolling content (top to bottom).
  final List<Widget> children;

  /// Replaces the default scrolling list (e.g. a reversed chat list). [children] are ignored.
  final Widget? body;

  /// Route to go to when Back is tapped and there is nothing to pop. Non-null shows a Back button
  /// instead of the profile button.
  final String? back;

  /// Custom back action (e.g. a flow step). Shows a Back button when set.
  final VoidCallback? onBack;

  /// Enables pull-to-refresh.
  final Future<void> Function()? onRefresh;

  /// Widget pinned under the scroll area (e.g. chat composer). On a phone it rides on top of the keyboard.
  final Widget? bottom;

  /// Max content width on desktop. Use double.infinity for full-width grids.
  final double maxWidth;
  final bool alwaysShowTitle;

  /// Right side of the nav bar (pass_v1 put the chat button here; the MVP has no chat).
  final Widget? trailing;

  @override
  State<PassScaffold> createState() => _PassScaffoldState();
}

class _PassScaffoldState extends State<PassScaffold> {
  bool _scrolled = false;

  bool _onScroll(ScrollNotification n) {
    if (n.depth != 0) return false;
    final s = n.metrics.pixels > 40;
    if (s != _scrolled) setState(() => _scrolled = s);
    return false;
  }

  void _goBack() {
    if (widget.onBack != null) return widget.onBack!();
    if (context.canPop()) {
      context.pop();
    } else {
      context.go(widget.back!);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final desktop = context.isDesktop;
    final inPane = DetailPane.of(context);
    final hasBack = (widget.back != null || widget.onBack != null) && !inPane;
    final showTitle = widget.alwaysShowTitle || _scrolled || desktop;
    final state = AppState.instance;

    final nav = Container(
      decoration: BoxDecoration(
        color: c.bgGrouped,
        boxShadow: _scrolled ? [BoxShadow(color: c.sep, offset: const Offset(0, PassSpace.hairline))] : null,
      ),
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      constraints: const BoxConstraints(minHeight: PassSpace.navHeight),
      child: Row(children: [
        Expanded(
          child: Align(
            alignment: Alignment.centerLeft,
            child: hasBack
                ? GlassCircleButton(
                    semanticLabel: 'Back',
                    onTap: _goBack,
                    child: SvgIcon(PassIcons.back,
                        color: c.label, viewBox: const Size(12, 20), width: 12, height: 20, stroke: 2.5),
                  )
                : (!desktop && state.me != null)
                    ? GlassCircleButton(
                        semanticLabel: 'Profile and settings',
                        onTap: () => context.go('/profile'),
                        child: Text(state.me!.initials,
                            style: PassText.subhead.copyWith(fontWeight: PassText.semibold, color: c.tint)),
                      )
                    : const SizedBox(height: PassSpace.glassButton),
          ),
        ),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 220),
          child: AnimatedOpacity(
            opacity: showTitle ? 1 : 0,
            duration: PassMotion.normal,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text(widget.title,
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: PassText.headline.copyWith(color: c.label)),
              if (widget.subtitle != null)
                Text(widget.subtitle!,
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: PassText.caption.copyWith(color: c.label2)),
            ]),
          ),
        ),
        Expanded(
          child: Align(
            alignment: Alignment.centerRight,
            child: widget.trailing ?? const SizedBox(height: PassSpace.glassButton),
          ),
        ),
      ]),
    );

    // Composer offset: keyboard height when it is up, else room for the tab bar (or just the home indicator).
    final keyboard = MediaQuery.viewInsetsOf(context).bottom;
    final double composerPad = desktop || inPane
        ? 0
        : keyboard > 0
            ? keyboard
            : hidesTabBar(GoRouterState.of(context).uri.path)
                ? MediaQuery.paddingOf(context).bottom
                : PassSpace.tabBarHeight + PassSpace.tabBarBottom + 8;

    final bottomPad = desktop ? PassSpace.xxxl : PassSpace.contentBottom;
    Widget list = ListView(
      physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
      padding: EdgeInsets.only(bottom: widget.bottom == null ? bottomPad : PassSpace.card),
      children: [
        for (final child in widget.children)
          desktop && widget.maxWidth.isFinite ? _Centered(maxWidth: widget.maxWidth, child: child) : child,
      ],
    );
    if (widget.body != null) {
      list = desktop && widget.maxWidth.isFinite ? _Centered(maxWidth: widget.maxWidth, child: widget.body!) : widget.body!;
    } else if (widget.onRefresh != null) {
      list = CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
        slivers: [
          CupertinoSliverRefreshControl(onRefresh: widget.onRefresh),
          SliverPadding(
            padding: EdgeInsets.only(bottom: widget.bottom == null ? bottomPad : PassSpace.card),
            sliver: SliverList.list(children: [
              for (final child in widget.children)
                desktop && widget.maxWidth.isFinite ? _Centered(maxWidth: widget.maxWidth, child: child) : child,
            ]),
          ),
        ],
      );
    }

    return ColoredBox(
      color: c.bgGrouped,
      child: SafeArea(
        bottom: false,
        child: Column(children: [
          nav,
          Expanded(child: NotificationListener<ScrollNotification>(onNotification: _onScroll, child: list)),
          if (widget.bottom != null)
            AnimatedPadding(
              padding: EdgeInsets.only(bottom: composerPad),
              duration: const Duration(milliseconds: 220),
              curve: Curves.easeOutCubic,
              child: desktop && widget.maxWidth.isFinite
                  ? _Centered(maxWidth: widget.maxWidth, child: widget.bottom!)
                  : widget.bottom!,
            ),
        ]),
      ),
    );
  }
}

class _Centered extends StatelessWidget {
  const _Centered({required this.maxWidth, required this.child});
  final double maxWidth;
  final Widget child;

  @override
  Widget build(BuildContext context) =>
      Center(child: ConstrainedBox(constraints: BoxConstraints(maxWidth: maxWidth), child: child));
}

/// Marks a subtree as the detail pane of a desktop master–detail layout (hides its Back button).
class DetailPane extends InheritedWidget {
  const DetailPane({super.key, required super.child});

  static bool of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<DetailPane>() != null;

  @override
  bool updateShouldNotify(DetailPane oldWidget) => false;
}

/// Desktop: list on the left, detail on the right. Phone: only [detail] (or [master] when detail is null).
class MasterDetail extends StatelessWidget {
  const MasterDetail({super.key, required this.master, this.detail, this.emptyText = 'Select an item'});
  final Widget master;
  final Widget? detail;
  final String emptyText;

  @override
  Widget build(BuildContext context) {
    if (!context.isDesktop) return detail ?? master;
    final c = context.c;
    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SizedBox(width: PassSpace.masterWidth, child: master),
      Container(width: PassSpace.hairline, color: c.sep),
      Expanded(
        child: detail == null
            ? ColoredBox(
                color: c.bgGrouped,
                child: Center(child: Text(emptyText, style: PassText.subhead.copyWith(color: c.label2))),
              )
            : DetailPane(child: detail!),
      ),
    ]);
  }
}
