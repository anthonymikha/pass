// Tiny SVG path renderer for the design's inline icons (tab icons, Apple logo, chevrons).
// Supports M L H V C S Q A Z (absolute and relative) — enough for every path in the design.
import 'package:flutter/widgets.dart';

Path parseSvgPath(String d) {
  final path = Path();
  final tokens = RegExp(r'[MmLlHhVvCcSsQqAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?').allMatches(d).map((m) => m[0]!).toList();
  var i = 0;
  var cmd = 'M';
  double x = 0, y = 0, sx = 0, sy = 0, cx = 0, cy = 0;
  bool isCmd(String t) => RegExp(r'^[A-Za-z]$').hasMatch(t);
  double n() => double.parse(tokens[i++]);
  while (i < tokens.length) {
    if (isCmd(tokens[i])) cmd = tokens[i++];
    final rel = cmd.toLowerCase() == cmd;
    final ox = rel ? x : 0.0, oy = rel ? y : 0.0;
    switch (cmd.toUpperCase()) {
      case 'M':
        x = ox + n();
        y = oy + n();
        path.moveTo(x, y);
        sx = x;
        sy = y;
        cmd = rel ? 'l' : 'L'; // subsequent pairs are line-tos
        cx = x;
        cy = y;
      case 'L':
        x = ox + n();
        y = oy + n();
        path.lineTo(x, y);
        cx = x;
        cy = y;
      case 'H':
        x = ox + n();
        path.lineTo(x, y);
        cx = x;
        cy = y;
      case 'V':
        y = oy + n();
        path.lineTo(x, y);
        cx = x;
        cy = y;
      case 'C':
        final x1 = ox + n(), y1 = oy + n(), x2 = ox + n(), y2 = oy + n();
        x = ox + n();
        y = oy + n();
        path.cubicTo(x1, y1, x2, y2, x, y);
        cx = x2;
        cy = y2;
      case 'S':
        final x1 = 2 * x - cx, y1 = 2 * y - cy;
        final x2 = ox + n(), y2 = oy + n();
        x = ox + n();
        y = oy + n();
        path.cubicTo(x1, y1, x2, y2, x, y);
        cx = x2;
        cy = y2;
      case 'Q':
        final x1 = ox + n(), y1 = oy + n();
        x = ox + n();
        y = oy + n();
        path.quadraticBezierTo(x1, y1, x, y);
        cx = x1;
        cy = y1;
      case 'A':
        final rx = n(), ry = n(), rot = n(), large = n() != 0, sweep = n() != 0;
        x = ox + n();
        y = oy + n();
        path.arcToPoint(Offset(x, y),
            radius: Radius.elliptical(rx, ry), rotation: rot, largeArc: large, clockwise: sweep);
        cx = x;
        cy = y;
      case 'Z':
        path.close();
        x = sx;
        y = sy;
        cx = x;
        cy = y;
      default:
        i++;
    }
  }
  return path;
}

/// Paints an SVG path scaled from its [viewBox] into [width]×[height].
class SvgIcon extends StatelessWidget {
  const SvgIcon(this.d,
      {super.key,
      required this.color,
      this.viewBox = const Size(24, 24),
      this.width = 24,
      this.height = 24,
      this.stroke,
      this.evenOdd = false});

  final String d;
  final Color color;
  final Size viewBox;
  final double width, height;

  /// Stroke width in viewBox units; null = filled.
  final double? stroke;
  final bool evenOdd;

  @override
  Widget build(BuildContext context) =>
      CustomPaint(size: Size(width, height), painter: _SvgPainter(d, color, viewBox, stroke, evenOdd));
}

class _SvgPainter extends CustomPainter {
  _SvgPainter(this.d, this.color, this.viewBox, this.stroke, this.evenOdd);
  final String d;
  final Color color;
  final Size viewBox;
  final double? stroke;
  final bool evenOdd;

  @override
  void paint(Canvas canvas, Size size) {
    final s = (size.width / viewBox.width).clamp(0.0, size.height / viewBox.height);
    canvas.translate((size.width - viewBox.width * s) / 2, (size.height - viewBox.height * s) / 2);
    canvas.scale(s);
    final path = parseSvgPath(d)..fillType = evenOdd ? PathFillType.evenOdd : PathFillType.nonZero;
    final paint = Paint()
      ..color = color
      ..isAntiAlias = true;
    if (stroke != null) {
      paint
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke!
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round;
    }
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(_SvgPainter old) => old.d != d || old.color != color || old.stroke != stroke;
}

/// Icon paths copied from the design (24×24 viewBox unless noted).
class PassIcons {
  static const home =
      'M12 3.2 2.6 10.6a1 1 0 0 0 1.2 1.6l.7-.5V20a1.5 1.5 0 0 0 1.5 1.5h3.5v-6h5v6H18a1.5 1.5 0 0 0 1.5-1.5v-8.3l.7.5a1 1 0 0 0 1.2-1.6z';
  static const play = 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 5h-2v4H7v2h4v4h2v-4h4v-2h-4z';
  static const schedule =
      'M7 2h2v2h6V2h2v2h2a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2zM5 9v10h14V9zm2 2h3v3H7z';
  static const clips =
      'M3 6.5A2.5 2.5 0 0 1 5.5 4h8A2.5 2.5 0 0 1 16 6.5v1.8l4.3-2.6A1.1 1.1 0 0 1 22 6.6v10.8a1.1 1.1 0 0 1-1.7.9L16 15.7v1.8a2.5 2.5 0 0 1-2.5 2.5h-8A2.5 2.5 0 0 1 3 17.5z';
  static const wellness =
      'M12 21s-7.5-4.6-9.6-9.3C1 8.5 3 4.5 6.8 4.5c2.2 0 3.6 1.2 5.2 3 1.6-1.8 3-3 5.2-3 3.8 0 5.8 4 4.4 7.2C19.5 16.4 12 21 12 21z';
  static const bell =
      'M12 22a2.5 2.5 0 0 0 2.5-2.5h-5A2.5 2.5 0 0 0 12 22zm7-6v-5a7 7 0 0 0-5.5-6.8v-.7a1.5 1.5 0 0 0-3 0v.7A7 7 0 0 0 5 11v5l-2 2v1h18v-1z';
  static const moon = 'M21 14.5A9 9 0 0 1 9.5 3a9 9 0 1 0 11.5 11.5z';
  static const card =
      'M2 6.5A2.5 2.5 0 0 1 4.5 4h15A2.5 2.5 0 0 1 22 6.5V8H2zm0 4h20v7a2.5 2.5 0 0 1-2.5 2.5h-15A2.5 2.5 0 0 1 2 17.5zM5 15v2h5v-2z';
  static const team =
      'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM1 20c0-3.9 3.6-7 8-7s8 3.1 8 7v1H1zm17.5 1v-1c0-2.2-.9-4.2-2.4-5.6.6-.2 1.3-.4 1.9-.4 3.3 0 6 2.3 6 5.3V21z';
  static const chat =
      'M12 3C6.5 3 2 6.6 2 11c0 2.4 1.3 4.6 3.4 6.1-.2 1.4-.9 2.8-2 3.8 2.3 0 4.3-.8 5.6-1.9 1 .3 2 .4 3 .4 5.5 0 10-3.6 10-8S17.5 3 12 3z';

  /// viewBox 20×24
  static const apple =
      'M16.4 12.6c0-2.4 2-3.6 2.1-3.7-1.1-1.7-2.9-1.9-3.5-1.9-1.5-.2-2.9.9-3.7.9-.8 0-1.9-.9-3.2-.8-1.6 0-3.1 1-4 2.4-1.7 3-.4 7.4 1.2 9.8.8 1.2 1.8 2.5 3 2.4 1.2 0 1.7-.8 3.1-.8s1.9.8 3.2.8c1.3 0 2.1-1.2 2.9-2.4.9-1.4 1.3-2.7 1.3-2.8 0 0-2.4-1-2.4-3.9zM14 5.4c.7-.8 1.1-1.9 1-3-1 0-2.1.7-2.8 1.5-.6.7-1.2 1.8-1 2.9 1.1.1 2.1-.6 2.8-1.4z';

  /// Stroked, viewBox 12×20, stroke 2.5
  static const back = 'M10 2L2 10l8 8';

  /// Stroked, viewBox 8×14, stroke 2
  static const chevronRight = 'M1 1l6 6-6 6';

  /// Stroked, viewBox 18×14, stroke 2.4
  static const check = 'M1.5 7.5l5 5L16.5 1.5';

  /// Stroked, viewBox 10×16, stroke 1.8 (picker up/down chevrons)
  static const updown = 'M2 6l3-3 3 3M2 10l3 3 3-3';
}
