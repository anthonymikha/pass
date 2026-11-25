// Row that slides left to reveal actions (88px each), as in Chats and Block-out times.
// On desktop (mouse), actions are also reachable with a trailing "…" button.
import 'package:flutter/cupertino.dart';

import '../theme/tokens.dart';
import 'controls.dart';

class SwipeAction {
  const SwipeAction(this.label, this.color, this.onTap);
  final String label;
  final Color color;
  final VoidCallback onTap;
}

class SwipeRow extends StatefulWidget {
  const SwipeRow({super.key, required this.child, required this.actions, this.background});
  final Widget child;
  final List<SwipeAction> actions;
  final Color? background;

  @override
  State<SwipeRow> createState() => _SwipeRowState();
}

class _SwipeRowState extends State<SwipeRow> {
  static const double actionWidth = 88;
  double _dx = 0;
  bool _dragging = false;

  double get _max => actionWidth * widget.actions.length;

  /// Actions are only drawn while the row is (or is sliding) open; drawn always, their colour bled through
  /// the card's anti-aliased rounded corner as a thin red line.
  bool _settling = false;

  void _close() => setState(() {
        _dx = 0;
        _settling = true;
      });

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return ClipRect(
      child: Stack(children: [
        if (_dx != 0 || _dragging || _settling)
        Positioned.fill(
          child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            for (final a in widget.actions)
              Pressable(
                onTap: () {
                  _close();
                  a.onTap();
                },
                child: Container(
                  width: actionWidth,
                  color: a.color,
                  alignment: Alignment.center,
                  child: Text(a.label,
                      style: PassText.subhead.copyWith(color: PassColors.white, fontWeight: PassText.semibold)),
                ),
              ),
          ]),
        ),
        GestureDetector(
          onHorizontalDragStart: (_) => setState(() => _dragging = true),
          onHorizontalDragUpdate: (d) => setState(() => _dx = (_dx + d.delta.dx).clamp(-_max - 24, 0)),
          onHorizontalDragEnd: (_) => setState(() {
            _dragging = false;
            _dx = _dx < -_max / 2 ? -_max : 0;
            _settling = true;
          }),
          child: AnimatedContainer(
            duration: _dragging ? Duration.zero : PassMotion.swipe,
            curve: PassMotion.swipeCurve,
            onEnd: () => setState(() => _settling = false),
            transform: Matrix4.translationValues(_dx, 0, 0),
            color: widget.background ?? c.bgCard,
            child: Row(children: [
              Expanded(child: widget.child),
              if (context.isDesktop)
                Pressable(
                  semanticLabel: 'More actions',
                  onTap: () => setState(() {
                    _dx = _dx == 0 ? -_max : 0;
                    _settling = true;
                  }),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: PassSpace.ml),
                    child: Text('•••', style: PassText.footnote.copyWith(color: c.label3)),
                  ),
                ),
            ]),
          ),
        ),
      ]),
    );
  }
}
