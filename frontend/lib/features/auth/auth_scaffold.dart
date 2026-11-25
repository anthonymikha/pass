// Shared frame for the auth and onboarding screens: no tab bar, a glass Back button only when [back] is set.
import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../../theme/tokens.dart';
import '../../widgets/controls.dart';
import '../../widgets/svg_icon.dart';

class AuthScaffold extends StatelessWidget {
  const AuthScaffold({super.key, required this.children, this.back, this.bottomAligned = false});

  final List<Widget> children;

  /// Route to go to when Back is tapped and there is nothing to pop. Null hides the Back button.
  final String? back;

  /// Pushes the content to the bottom of the screen (Welcome).
  final bool bottomAligned;

  static const _bottomPad = 44.0; // design: padding-bottom 44

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return ColoredBox(
      color: c.bgGrouped,
      child: SafeArea(
        bottom: false,
        child: Column(children: [
          Container(
            alignment: Alignment.centerLeft,
            constraints: const BoxConstraints(minHeight: PassSpace.navHeight),
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: back == null
                ? const SizedBox(height: PassSpace.glassButton)
                : GlassCircleButton(
                    semanticLabel: 'Back',
                    onTap: () => context.canPop() ? context.pop() : context.go(back!),
                    child: SvgIcon(PassIcons.back,
                        color: c.label, viewBox: const Size(12, 20), width: 12, height: 20, stroke: 2.5),
                  ),
          ),
          Expanded(
            child: LayoutBuilder(
              builder: (context, box) => SingleChildScrollView(
                physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
                padding: const EdgeInsets.only(bottom: _bottomPad),
                child: Center(
                  child: ConstrainedBox(
                    constraints: BoxConstraints(
                        minHeight: math.max(0, box.maxHeight - _bottomPad), maxWidth: PassSpace.formMaxWidth),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      mainAxisAlignment: bottomAligned ? MainAxisAlignment.end : MainAxisAlignment.start,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: children,
                    ),
                  ),
                ),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}

/// Large title (34 Bold) with a 17px subtitle, as on every auth screen.
class AuthHeader extends StatelessWidget {
  const AuthHeader(this.title, this.subtitle, {super.key});
  final String title, subtitle;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(PassSpace.gutter, 4, PassSpace.gutter, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: PassText.largeTitle.copyWith(color: context.c.label)),
          Padding(
            padding: const EdgeInsets.only(top: PassSpace.xs),
            child: Text(subtitle, style: PassText.body.copyWith(color: context.c.label2)),
          ),
        ]),
      );
}

/// Margin of the screen's primary button (design: 20 side, [top] above).
EdgeInsets authButtonMargin(double top) => EdgeInsets.fromLTRB(PassSpace.gutter, top, PassSpace.gutter, 0);
