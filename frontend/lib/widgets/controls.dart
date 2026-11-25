// Small shared controls: buttons, segmented control, switch, check circle, pills, avatar, glass button.
import 'package:flutter/cupertino.dart';

import '../theme/tokens.dart';
import 'svg_icon.dart';

/// Pressable area with iOS press feedback: dims to .7 and shrinks a few points (less for wide rows),
/// then springs back on release. Shows a hover cursor.
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.semanticLabel});
  final Widget child;
  final VoidCallback? onTap;
  final String? semanticLabel;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;
  double _pressedScale = .96;

  void _press(bool down) {
    if (down) {
      // ~3pt shrink on a 375pt row, 4% on a button.
      final s = context.size;
      final side = s == null ? 44.0 : (s.width > s.height ? s.width : s.height);
      _pressedScale = 1 - (6 / side).clamp(.008, .04);
    }
    setState(() => _down = down);
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onTap != null;
    return Semantics(
      button: true,
      enabled: enabled,
      label: widget.semanticLabel,
      child: MouseRegion(
        cursor: enabled ? SystemMouseCursors.click : SystemMouseCursors.basic,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: widget.onTap,
          onTapDown: enabled ? (_) => _press(true) : null,
          onTapUp: enabled ? (_) => _press(false) : null,
          onTapCancel: enabled ? () => _press(false) : null,
          child: AnimatedScale(
            scale: _down ? _pressedScale : 1,
            duration: _down ? PassMotion.fast : PassMotion.snappy.duration,
            curve: _down ? Curves.easeOut : PassMotion.snappy,
            child: AnimatedOpacity(
              opacity: _down ? .7 : 1,
              duration: _down ? PassMotion.fast : PassMotion.normal,
              child: widget.child,
            ),
          ),
        ),
      ),
    );
  }
}

enum PassButtonKind { primary, secondary, dark, fill, card }

/// Full-width pill button. primary = tint/white, secondary = tint-bg/tint,
/// dark = label/label-inv, fill = fill/tint, card = bg-card/tint-ink.
class PassButton extends StatelessWidget {
  const PassButton(this.label,
      {super.key,
      this.onPressed,
      this.kind = PassButtonKind.primary,
      this.enabled = true,
      this.leading,
      this.margin = const EdgeInsets.symmetric(horizontal: PassSpace.gutter),
      this.busy = false});

  final String label;
  final VoidCallback? onPressed;
  final PassButtonKind kind;

  /// When false the button shows at opacity .4 and ignores taps (design "not ready" state).
  final bool enabled;
  final Widget? leading;
  final EdgeInsetsGeometry margin;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (bg, fg) = switch (kind) {
      PassButtonKind.primary => (c.tint, PassColors.white),
      PassButtonKind.secondary => (c.tintBg, c.tint),
      PassButtonKind.dark => (c.label, c.labelInv),
      PassButtonKind.fill => (c.fill, c.tint),
      PassButtonKind.card => (c.bgCard, c.tintInk),
    };
    final active = enabled && !busy && onPressed != null;
    return Padding(
      padding: margin,
      child: Opacity(
        opacity: enabled ? 1 : .4,
        child: Pressable(
          onTap: active ? onPressed : null,
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 15, horizontal: PassSpace.gutter),
            decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(PassRadii.pill)),
            child: busy
                ? CupertinoActivityIndicator(color: fg, radius: 10.5)
                : Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    if (leading != null) ...[leading!, const SizedBox(width: PassSpace.sm)],
                    Flexible(
                      child: Text(label,
                          textAlign: TextAlign.center,
                          style: PassText.headline.copyWith(color: fg, height: 22 / 17)),
                    ),
                  ]),
          ),
        ),
      ),
    );
  }
}

/// "Continue with Apple" style button with the Apple logo (dark variant).
class AppleButton extends StatelessWidget {
  const AppleButton(this.label, {super.key, required this.onPressed, this.margin = EdgeInsets.zero});
  final String label;
  final VoidCallback onPressed;
  final EdgeInsetsGeometry margin;

  @override
  Widget build(BuildContext context) => PassButton(label,
      kind: PassButtonKind.dark,
      onPressed: onPressed,
      margin: margin,
      leading: SvgIcon(PassIcons.apple, color: context.c.labelInv, viewBox: const Size(20, 24), width: 18, height: 20));
}

/// Inline text link: 15 tint by default ("Book another", "+ Add", "Cancel").
class PassLink extends StatelessWidget {
  const PassLink(this.label, {super.key, this.onTap, this.style, this.color, this.padding = EdgeInsets.zero});
  final String label;
  final VoidCallback? onTap;
  final TextStyle? style;
  final Color? color;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: Padding(
          padding: padding,
          child: Text(label, style: (style ?? PassText.subhead).copyWith(color: color ?? context.c.tint)),
        ),
      );
}

/// Segmented control: fill track, 3px padding, pill; selected segment uses seg-sel pill.
class PassSegmented<T> extends StatelessWidget {
  const PassSegmented(
      {super.key,
      required this.values,
      required this.labelOf,
      required this.selected,
      required this.onChanged,
      this.fontSize = 15,
      this.verticalPadding = 9,
      this.margin = const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.l, PassSpace.gutter, 0)});

  final List<T> values;
  final String Function(T) labelOf;
  final T selected;
  final ValueChanged<T> onChanged;
  final double fontSize;
  final double verticalPadding;
  final EdgeInsetsGeometry margin;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final i = values.indexOf(selected);
    final n = values.length;
    return Padding(
      padding: margin,
      child: Container(
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(PassRadii.pill)),
        child: Stack(children: [
          // iOS segmented control: one thumb slides between segments.
          Positioned.fill(
            child: AnimatedOpacity(
              opacity: i < 0 ? 0 : 1,
              duration: PassMotion.fast,
              child: AnimatedAlign(
                alignment: Alignment(n < 2 || i < 0 ? 0 : -1 + 2 * i / (n - 1), 0),
                duration: PassMotion.snappy.duration,
                curve: PassMotion.snappy,
                child: FractionallySizedBox(
                  widthFactor: 1 / n,
                  heightFactor: 1,
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: c.segSel,
                      borderRadius: BorderRadius.circular(PassRadii.pill),
                      boxShadow: const [BoxShadow(color: Color(0x14000000), blurRadius: 4, offset: Offset(0, 1))],
                    ),
                  ),
                ),
              ),
            ),
          ),
          Row(children: [
            for (final v in values)
              Expanded(
                child: Pressable(
                  onTap: () => onChanged(v),
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: verticalPadding, horizontal: 8),
                    child: Text(labelOf(v),
                        textAlign: TextAlign.center,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style:
                            PassText.subhead.copyWith(fontSize: fontSize, fontWeight: PassText.medium, color: c.label)),
                  ),
                ),
              ),
          ]),
        ]),
      ),
    );
  }
}

/// iOS-style switch at the design size: 63×28 track, 37×24 knob.
class PassSwitch extends StatelessWidget {
  const PassSwitch({super.key, required this.value, required this.onChanged});
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Semantics(
      toggled: value,
      child: Pressable(
        onTap: onChanged == null ? null : () => onChanged!(!value),
        child: AnimatedContainer(
          duration: PassMotion.normal,
          curve: Curves.easeOut,
          width: 63,
          height: 28,
          padding: const EdgeInsets.all(2),
          decoration:
              BoxDecoration(color: value ? c.tint : c.fill2, borderRadius: BorderRadius.circular(PassRadii.pill)),
          child: AnimatedAlign(
            duration: PassMotion.snappy.duration,
            curve: PassMotion.snappy,
            alignment: value ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              width: 37,
              height: 24,
              decoration: BoxDecoration(
                color: PassColors.white,
                borderRadius: BorderRadius.circular(PassRadii.pill),
                boxShadow: const [BoxShadow(color: Color(0x2E000000), blurRadius: 4, offset: Offset(0, 2))],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 22px check circle: 1.5px tint border, filled tint when selected.
class CheckCircle extends StatelessWidget {
  const CheckCircle({super.key, required this.selected, this.size = 22});
  final bool selected;
  final double size;

  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        key: ValueKey(selected),
        tween: Tween(begin: selected ? .8 : 1, end: 1),
        duration: PassMotion.bouncy.duration,
        curve: PassMotion.bouncy,
        builder: (context, s, child) => Transform.scale(scale: s, child: child),
        child: AnimatedContainer(
        duration: PassMotion.fast,
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: selected ? context.c.tint : PassColors.transparent,
          border: Border.all(color: context.c.tint, width: 1.5),
        ),
      ),
      );
}

/// 16px radio dot used in the "With" list.
class RadioDot extends StatelessWidget {
  const RadioDot({super.key, required this.selected});
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      width: 16,
      height: 16,
      decoration: BoxDecoration(
          shape: BoxShape.circle, border: Border.all(color: selected ? c.tint : c.sep, width: 1.5), color: c.bgCard),
      padding: const EdgeInsets.all(2.5),
      child: DecoratedBox(
          decoration: BoxDecoration(shape: BoxShape.circle, color: selected ? c.tint : PassColors.transparent)),
    );
  }
}

/// Checkmark (settings/appearance/roles). Invisible when not [visible] so rows keep their width.
class CheckMark extends StatelessWidget {
  const CheckMark({super.key, required this.visible});
  final bool visible;

  @override
  Widget build(BuildContext context) => Opacity(
        opacity: visible ? 1 : 0,
        child: SvgIcon(PassIcons.check,
            color: context.c.tint, viewBox: const Size(18, 14), width: 18, height: 14, stroke: 2.4),
      );
}

/// Right chevron for navigation rows.
class Chevron extends StatelessWidget {
  const Chevron({super.key});

  @override
  Widget build(BuildContext context) =>
      SvgIcon(PassIcons.chevronRight, color: context.c.label3, viewBox: const Size(8, 14), width: 8, height: 14, stroke: 2);
}

/// Tag pill: 12–13 Semibold, padding 3/9, pill.
class TagPill extends StatelessWidget {
  const TagPill(this.text, {super.key, required this.fg, required this.bg, this.fontSize = 12});
  final String text;
  final Color fg, bg;
  final double fontSize;

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.symmetric(vertical: fontSize > 12 ? 4 : 3, horizontal: fontSize > 12 ? 10 : 9),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(PassRadii.pill)),
        child: Text(text,
            maxLines: 1, style: PassText.caption.copyWith(fontSize: fontSize, fontWeight: PassText.semibold, color: fg)),
      );
}

/// Small square-ish chip (amenities, "4 tags"): 12px, padding 3/8, radius 6.
class SmallChip extends StatelessWidget {
  const SmallChip(this.text, {super.key, this.fg, this.bg});
  final String text;
  final Color? fg, bg;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 8),
        decoration: BoxDecoration(color: bg ?? context.c.fill, borderRadius: BorderRadius.circular(PassRadii.tag)),
        child: Text(text, style: PassText.caption.copyWith(color: fg ?? context.c.label2)),
      );
}

/// Round initials avatar.
class Avatar extends StatelessWidget {
  const Avatar(this.initials, {super.key, this.size = 44, this.bg, this.fg, this.fontSize});
  final String initials;
  final double size;
  final Color? bg, fg;
  final double? fontSize;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(shape: BoxShape.circle, color: bg ?? context.c.fill3),
        child: Text(initials,
            style: PassText.subhead.copyWith(
                fontSize: fontSize ?? (size * .34).clamp(12, 34).toDouble(),
                fontWeight: PassText.semibold,
                color: fg ?? context.c.label)),
      );
}

/// 30/36px rounded-square icon used in settings and onboarding rows.
class IconTile extends StatelessWidget {
  const IconTile(this.path, {super.key, required this.color, this.size = 30, this.radius = 8});
  final String path;
  final Color color;
  final double size, radius;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(radius)),
        child: SvgIcon(path, color: PassColors.white, width: size * .6, height: size * .6),
      );
}

/// Glass container (nav buttons, tab bar). ponytail: no live BackdropFilter blur: on mobile browsers it
/// re-renders everything behind it every frame (the main cause of scroll/tab jank); a near-opaque fill
/// looks the same over the plain grouped background.
class Glass extends StatelessWidget {
  const Glass({super.key, required this.child, this.radius = PassRadii.pill, this.padding});
  final Widget child;
  final double radius;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: c.glassBg,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: c.glassEdge, width: PassSpace.hairline),
        boxShadow: c.glassShadow,
      ),
      child: child,
    );
  }
}

/// 44px glass circle button (Back / profile initials / chats).
class GlassCircleButton extends StatelessWidget {
  const GlassCircleButton({super.key, required this.child, required this.onTap, required this.semanticLabel});
  final Widget child;
  final VoidCallback onTap;
  final String semanticLabel;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        semanticLabel: semanticLabel,
        child: SizedBox(
          width: PassSpace.glassButton,
          height: PassSpace.glassButton,
          child: Glass(child: Center(child: child)),
        ),
      );
}

/// −/+ stepper (RPE duration): fill pill 32 high, 47px halves.
class PassStepper extends StatelessWidget {
  const PassStepper({super.key, required this.onMinus, required this.onPlus});
  final VoidCallback? onMinus, onPlus;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    Widget half(String t, VoidCallback? f, String label) => Pressable(
          onTap: f,
          semanticLabel: label,
          child: SizedBox(
              width: 47,
              height: 32,
              child: Center(child: Text(t, style: PassText.title2.copyWith(fontWeight: PassText.regular, color: c.label)))),
        );
    return Container(
      height: 32,
      decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(PassRadii.pill)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        half('−', onMinus, 'Decrease'),
        Container(width: 1, height: 18, color: c.sep),
        half('+', onPlus, 'Increase'),
      ]),
    );
  }
}
