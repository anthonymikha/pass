// Shared layout pieces: grouped cards, rows, headers, banners, tiles, inputs, charts, placeholders.
import 'package:flutter/cupertino.dart';

import '../theme/tokens.dart';
import 'controls.dart';
import 'svg_icon.dart';

const EdgeInsets kGutter = EdgeInsets.symmetric(horizontal: PassSpace.gutter);

/// Grouped list card (bg-card, r26). Children are separated by 0.5px lines; the last has none.
/// [inset] = horizontal padding inside the card where separators also start (16 for lists, 0 for form rows).
class GroupedCard extends StatelessWidget {
  const GroupedCard(
      {super.key,
      required this.children,
      this.inset = PassSpace.card,
      this.margin = kGutter,
      this.color,
      this.radius = PassRadii.card,
      this.separators = true});

  final List<Widget> children;
  final double inset;
  final EdgeInsetsGeometry margin;
  final Color? color;
  final double radius;
  final bool separators;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final rows = <Widget>[];
    for (var i = 0; i < children.length; i++) {
      rows.add(children[i]);
      if (separators && i < children.length - 1) rows.add(Container(height: PassSpace.hairline, color: c.sep));
    }
    return Padding(
      padding: margin,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: Container(
          color: color ?? c.bgCard,
          padding: EdgeInsets.symmetric(horizontal: inset),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: rows),
        ),
      ),
    );
  }
}

/// Simple card (bg-card) with padding; used for notices and tiles.
class PassCard extends StatelessWidget {
  const PassCard(
      {super.key,
      required this.child,
      this.padding = const EdgeInsets.all(PassSpace.card),
      this.margin = kGutter,
      this.radius = PassRadii.tile,
      this.color});

  final Widget child;
  final EdgeInsetsGeometry padding, margin;
  final double radius;
  final Color? color;

  @override
  Widget build(BuildContext context) => Padding(
        padding: margin,
        child: Container(
          padding: padding,
          decoration: BoxDecoration(color: color ?? context.c.bgCard, borderRadius: BorderRadius.circular(radius)),
          child: child,
        ),
      );
}

enum NoticeKind { card, tint, inverse }

/// Notice banner r22, 15px: "**Recovery check.** Recovery 72% — …".
class NoticeBanner extends StatelessWidget {
  const NoticeBanner({super.key, this.bold, required this.text, this.kind = NoticeKind.card, this.margin = kGutter});
  final String? bold;
  final String text;
  final NoticeKind kind;
  final EdgeInsetsGeometry margin;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (bg, fg) = switch (kind) {
      NoticeKind.card => (c.bgCard, c.label),
      NoticeKind.tint => (c.tintBg, c.tintInk),
      NoticeKind.inverse => (c.inverseBg, c.inverseFg),
    };
    return Padding(
      padding: margin,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: PassSpace.ml, horizontal: PassSpace.l),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(PassRadii.notice)),
        child: Text.rich(
          TextSpan(children: [
            if (bold != null) TextSpan(text: '$bold ', style: const TextStyle(fontWeight: PassText.bold)),
            TextSpan(text: text),
          ]),
          style: PassText.subhead.copyWith(color: fg, height: 1.35),
        ),
      ),
    );
  }
}

/// Screen header: optional kicker (15 Semibold tint), large title, optional subtitle and trailing widget.
class LargeTitleHeader extends StatelessWidget {
  const LargeTitleHeader(
      {super.key,
      this.kicker,
      required this.title,
      this.subtitle,
      this.trailing,
      this.padding = const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.l, PassSpace.gutter, 0),
      this.kickerSize = 15});

  final String? kicker;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;
  final double kickerSize;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final col = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (kicker != null)
        Text(kicker!, style: PassText.subhead.copyWith(fontSize: kickerSize, fontWeight: PassText.semibold, color: c.tint)),
      Padding(
        padding: EdgeInsets.only(top: kicker != null ? 2 : 0),
        child: Text(title, style: PassText.largeTitle.copyWith(color: c.label)),
      ),
      if (subtitle != null)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(subtitle!, style: PassText.subhead.copyWith(color: c.label2)),
        ),
    ]);
    return Padding(
      padding: padding,
      child: trailing == null
          ? col
          : Row(crossAxisAlignment: CrossAxisAlignment.end, children: [Expanded(child: col), trailing!]),
    );
  }
}

/// Section header "Leaderboard · Friends" (20 Bold) with optional trailing link.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title,
      {super.key,
      this.trailing,
      this.padding = const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.gutter, PassSpace.gutter, PassSpace.s)});
  final String title;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) => Padding(
        padding: padding,
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(child: Text(title, style: PassText.title3.copyWith(color: context.c.label))),
          if (trailing != null) trailing!,
        ]),
      );
}

/// Uppercase caption header "WITH", "SLOTS AT …" (12, label2).
class CapsHeader extends StatelessWidget {
  const CapsHeader(this.text,
      {super.key,
      this.padding = const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.lg, PassSpace.gutter, PassSpace.s),
      this.fontSize = 12});
  final String text;
  final EdgeInsetsGeometry padding;
  final double fontSize;

  @override
  Widget build(BuildContext context) => Padding(
        padding: padding,
        child: Text(text.toUpperCase(), style: PassText.caption.copyWith(fontSize: fontSize, color: context.c.label2)),
      );
}

/// Footer/help text under groups (13, label2, padding 6 36 0).
class FootnoteText extends StatelessWidget {
  const FootnoteText(this.text,
      {super.key, this.padding = const EdgeInsets.fromLTRB(36, PassSpace.s, 36, 0), this.color});
  final String text;
  final EdgeInsetsGeometry padding;
  final Color? color;

  @override
  Widget build(BuildContext context) => Padding(
        padding: padding,
        child: Text(text, style: PassText.footnote.copyWith(color: color ?? context.c.label2, height: 18 / 13)),
      );
}

/// Settings-style row (min height 52): optional leading, label, value, trailing (switch/chevron/check).
class ListRow extends StatelessWidget {
  const ListRow(
      {super.key,
      this.leading,
      required this.label,
      this.value,
      this.trailing,
      this.onTap,
      this.labelColor,
      this.center = false,
      this.padding = const EdgeInsets.symmetric(horizontal: PassSpace.card)});

  final Widget? leading;
  final String label;
  final String? value;
  final Widget? trailing;
  final VoidCallback? onTap;
  final Color? labelColor;
  final bool center;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final row = ConstrainedBox(
      constraints: const BoxConstraints(minHeight: PassSpace.rowHeight),
      child: Padding(
        padding: padding,
        child: Row(mainAxisAlignment: center ? MainAxisAlignment.center : MainAxisAlignment.start, children: [
          if (leading != null) ...[leading!, const SizedBox(width: PassSpace.ml)],
          if (center)
            Text(label, style: PassText.body.copyWith(color: labelColor ?? c.label))
          else
            Expanded(child: Text(label, style: PassText.body.copyWith(color: labelColor ?? c.label))),
          if (value != null) ...[
            const SizedBox(width: PassSpace.ml),
            Text(value!, style: PassText.body.copyWith(color: c.label2)),
          ],
          if (trailing != null) ...[const SizedBox(width: PassSpace.ml), trailing!],
        ]),
      ),
    );
    return onTap == null ? row : Pressable(onTap: onTap, child: row);
  }
}

/// Form row: fixed-width label, right-aligned text field (Edit profile, block-out, tag form).
class FormFieldRow extends StatelessWidget {
  const FormFieldRow(
      {super.key,
      this.label,
      required this.controller,
      this.placeholder,
      this.labelWidth = 96,
      this.keyboardType,
      this.obscure = false,
      this.alignEnd = true,
      this.valueColor,
      this.autofillHints,
      this.onChanged,
      this.onSubmitted,
      this.textInputAction});

  final String? label;
  final TextEditingController controller;
  final String? placeholder;
  final double labelWidth;
  final TextInputType? keyboardType;
  final bool obscure, alignEnd;
  final Color? valueColor;
  final Iterable<String>? autofillHints;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final TextInputAction? textInputAction;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: PassSpace.rowHeight),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: PassSpace.card),
        child: Row(children: [
          if (label != null)
            SizedBox(width: labelWidth, child: Text(label!, style: PassText.body.copyWith(color: c.label))),
          if (label != null) const SizedBox(width: PassSpace.ml),
          Expanded(
            child: CupertinoTextField.borderless(
              controller: controller,
              placeholder: placeholder,
              keyboardType: keyboardType,
              obscureText: obscure,
              autofillHints: autofillHints,
              onChanged: onChanged,
              onSubmitted: onSubmitted,
              textInputAction: textInputAction,
              textAlign: alignEnd && label != null ? TextAlign.right : TextAlign.left,
              padding: const EdgeInsets.symmetric(vertical: PassSpace.l),
              style: PassText.body.copyWith(color: valueColor ?? (label != null ? c.label2 : c.label)),
              placeholderStyle: PassText.body.copyWith(color: c.label3),
              cursorColor: c.tint,
            ),
          ),
        ]),
      ),
    );
  }
}

/// Filled rounded input (search, message, notes): r16, fill background, 17px.
class PassInput extends StatelessWidget {
  const PassInput(
      {super.key,
      required this.controller,
      this.placeholder,
      this.onChanged,
      this.onSubmitted,
      this.margin = kGutter,
      this.textInputAction,
      this.autofocus = false});

  final TextEditingController controller;
  final String? placeholder;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final EdgeInsetsGeometry margin;
  final TextInputAction? textInputAction;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: margin,
      child: CupertinoTextField(
        controller: controller,
        placeholder: placeholder,
        onChanged: onChanged,
        onSubmitted: onSubmitted,
        textInputAction: textInputAction,
        autofocus: autofocus,
        padding: const EdgeInsets.symmetric(vertical: 11, horizontal: 14),
        decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(PassRadii.chip)),
        style: PassText.body.copyWith(color: c.label),
        placeholderStyle: PassText.body.copyWith(color: c.label3),
        cursorColor: c.tint,
      ),
    );
  }
}

/// Row with a value and up/down chevrons that opens a Cupertino picker ("Day", "Play type").
class PickerRow extends StatelessWidget {
  const PickerRow({super.key, required this.label, required this.options, required this.value, required this.onChanged});
  final String label;
  final List<String> options;
  final String value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return ListRow(
      label: label,
      onTap: () => showPicker(context),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        Text(value, style: PassText.body.copyWith(color: c.label2)),
        const SizedBox(width: PassSpace.s),
        SvgIcon(PassIcons.updown, color: c.label2, viewBox: const Size(10, 16), width: 10, height: 16, stroke: 1.8),
      ]),
    );
  }

  Future<void> showPicker(BuildContext context) async {
    var index = options.indexOf(value).clamp(0, options.length - 1);
    await showCupertinoModalPopup<void>(
      context: context,
      builder: (ctx) => Container(
        height: 260,
        color: ctx.c.bgCard,
        child: SafeArea(
          top: false,
          child: Column(children: [
            Align(
              alignment: Alignment.centerRight,
              child: PassLink('Done',
                  padding: const EdgeInsets.all(PassSpace.card),
                  style: PassText.headline,
                  onTap: () => Navigator.of(ctx).pop()),
            ),
            Expanded(
              child: CupertinoPicker(
                itemExtent: 36,
                scrollController: FixedExtentScrollController(initialItem: index),
                onSelectedItemChanged: (i) => index = i,
                children: [for (final o in options) Center(child: Text(o, style: PassText.body.copyWith(color: ctx.c.label)))],
              ),
            ),
          ]),
        ),
      ),
    );
    if (options[index] != value) onChanged(options[index]);
  }
}

/// Stat tile (r24): kicker 15 Semibold tint, then any content, then note 13 label2.
class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.kicker, required this.child, this.note, this.onTap});
  final String kicker;
  final Widget child;
  final String? note;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final tile = Container(
      padding: const EdgeInsets.all(PassSpace.card),
      decoration: BoxDecoration(color: c.bgCard, borderRadius: BorderRadius.circular(PassRadii.tile)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(kicker, style: PassText.subhead.copyWith(fontWeight: PassText.semibold, color: c.tint)),
        const SizedBox(height: PassSpace.sm),
        child,
        if (note != null) ...[
          const SizedBox(height: PassSpace.s),
          Text(note!, style: PassText.footnote.copyWith(color: c.label2)),
        ],
      ]),
    );
    return onTap == null ? tile : Pressable(onTap: onTap, child: tile);
  }
}

/// Big stat numeral with unit: "72" + "%".
class StatValue extends StatelessWidget {
  const StatValue(this.value, {super.key, this.unit, this.color});
  final String value;
  final String? unit;
  final Color? color;

  @override
  Widget build(BuildContext context) => Text.rich(
        TextSpan(children: [
          TextSpan(text: value),
          if (unit != null) TextSpan(text: unit, style: PassText.statUnit),
        ]),
        style: PassText.stat.copyWith(color: color ?? context.c.label),
      );
}

/// Bottom-aligned bar chart (Load · 7 d, sleep, trends). [values] are 0..1 heights.
class MiniBars extends StatelessWidget {
  const MiniBars(
      {super.key, required this.values, required this.colors, this.height = 44, this.gap = 3, this.radius = 4});
  final List<double> values;
  final List<Color> colors;
  final double height, gap, radius;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: height,
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          for (var i = 0; i < values.length; i++) ...[
            if (i > 0) SizedBox(width: gap),
            Expanded(
              child: Container(
                height: (values[i].clamp(0.0, 1.0) * height).clamp(3.0, height), // 3px stub for zero days
                decoration: BoxDecoration(color: colors[i], borderRadius: BorderRadius.circular(radius)),
              ),
            ),
          ],
        ]),
      );
}

/// Diagonal striped placeholder (clip thumbnails and the player).
class StripedBox extends StatelessWidget {
  const StripedBox({super.key, this.stripe = 4, this.radius = PassRadii.thumb, this.child});
  final double stripe, radius;
  final Widget? child;

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: CustomPaint(painter: _Stripes(context.c.fill3, context.c.fill, stripe), child: child),
      );
}

class _Stripes extends CustomPainter {
  _Stripes(this.a, this.b, this.w);
  final Color a, b;
  final double w;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = a);
    final p = Paint()
      ..color = b
      ..strokeWidth = w * 0.7071;
    final step = w * 2 * 0.7071 * 2;
    for (double x = -size.height; x < size.width + size.height; x += step) {
      canvas.drawLine(Offset(x, size.height), Offset(x + size.height, 0), p);
    }
  }

  @override
  bool shouldRepaint(_Stripes old) => old.a != a || old.b != b;
}

/// "or" divider with hairlines.
class OrDivider extends StatelessWidget {
  const OrDivider({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.all(PassSpace.gutter),
      child: Row(children: [
        Expanded(child: Container(height: PassSpace.hairline, color: c.sep)),
        Padding(
            padding: const EdgeInsets.symmetric(horizontal: PassSpace.ml),
            child: Text('or', style: PassText.footnote.copyWith(color: c.label2))),
        Expanded(child: Container(height: PassSpace.hairline, color: c.sep)),
      ]),
    );
  }
}

/// Legend item: small square + label (Free / Blocked / Session).
class LegendDot extends StatelessWidget {
  const LegendDot({super.key, required this.color, required this.label, this.round = false, this.border});
  final Color color;
  final String label;
  final bool round;
  final Color? border;

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            color: color,
            shape: round ? BoxShape.circle : BoxShape.rectangle,
            border: border == null ? null : Border.all(color: border!, width: PassSpace.hairline),
          ),
        ),
        const SizedBox(width: 5),
        Text(label, style: PassText.caption.copyWith(color: context.c.label2)),
      ]);
}

/// Constrains content width on desktop (forms, flows).
class MaxWidth extends StatelessWidget {
  const MaxWidth({super.key, required this.child, this.width = PassSpace.formMaxWidth});
  final Widget child;
  final double width;

  @override
  Widget build(BuildContext context) =>
      Center(child: ConstrainedBox(constraints: BoxConstraints(maxWidth: width), child: child));
}
