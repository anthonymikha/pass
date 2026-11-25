// Design tokens for PASS. The single source for colours, type, spacing and radii.
// Values come from the design export (CSS custom properties in PASS App v2.dc.html).
// Screens must use these tokens; no hard-coded colours or sizes elsewhere.
import 'dart:math' show pi;

import 'package:flutter/cupertino.dart';
import 'package:flutter/physics.dart';

/// Colour palette for one appearance (light or dark).
class PassColors {
  const PassColors({
    required this.bgGrouped,
    required this.bgCard,
    required this.label,
    required this.label2,
    required this.label3,
    required this.labelInv,
    required this.sep,
    required this.fill,
    required this.fill2,
    required this.fill3,
    required this.gray2,
    required this.gray3,
    required this.tint,
    required this.tintPress,
    required this.tintBg,
    required this.tintInk,
    required this.inverseBg,
    required this.inverseFg,
    required this.segSel,
    required this.tabSel,
    required this.glassBg,
    required this.glassEdge,
    required this.alertBg,
    required this.glassShadow,
    required this.brightness,
  });

  final Color bgGrouped, bgCard, label, label2, label3, labelInv, sep, fill, fill2, fill3;
  final Color gray2, gray3, tint, tintPress, tintBg, tintInk, inverseBg, inverseFg;
  final Color segSel, tabSel, glassBg, glassEdge, alertBg;
  final List<BoxShadow> glassShadow;
  final Brightness brightness;

  // Same in both appearances.
  static const Color white = Color(0xFFFFFFFF);
  static const Color black = Color(0xFF000000);
  static const Color destructive = Color(0xFFFF3B30);
  static const Color systemGray = Color(0xFF8E8E93);
  static const Color systemGreen = Color(0xFF34C759);
  static const Color systemIndigo = Color(0xFF5E5CE6);
  static const Color transparent = Color(0x00000000);

  /// Kicker colour on inverse (dark) cards: "#ff9783".
  static const Color tintInkOnDark = Color(0xFFFF9783);

  /// Scrim behind alerts.
  static const Color scrim = Color(0x47000000);

  static const light = PassColors(
    brightness: Brightness.light,
    bgGrouped: Color(0xFFF2F2F7),
    bgCard: Color(0xFFFFFFFF),
    label: Color(0xFF000000),
    label2: Color(0x993C3C43),
    label3: Color(0x4D3C3C43),
    labelInv: Color(0xFFFFFFFF),
    sep: Color(0x383C3C43),
    fill: Color(0x1F767680),
    fill2: Color(0x33787880),
    fill3: Color(0xFFF2F2F7),
    gray2: Color(0xFFAEAEB2),
    gray3: Color(0xFFC7C7CC),
    tint: Color(0xFFEC3013),
    tintPress: Color(0xFFC92A10),
    tintBg: Color(0x1FEC3013),
    tintInk: Color(0xFFB32008),
    inverseBg: Color(0xFF1C1C1E),
    inverseFg: Color(0xFFFFFFFF),
    segSel: Color(0xFFFFFFFF),
    tabSel: Color(0x29767680),
    glassBg: Color(0xF0FFFFFF), // design 55% + blur; opaque-ish without live blur (web perf)
    glassEdge: Color(0x0F000000),
    alertBg: Color(0xFAFFFFFF),
    glassShadow: [
      BoxShadow(color: Color(0x12000000), blurRadius: 3, offset: Offset(0, 1)),
      BoxShadow(color: Color(0x0F000000), blurRadius: 10, offset: Offset(0, 3)),
    ],
  );

  static const dark = PassColors(
    brightness: Brightness.dark,
    bgGrouped: Color(0xFF000000),
    bgCard: Color(0xFF1C1C1E),
    label: Color(0xFFFFFFFF),
    label2: Color(0x99EBEBF5),
    label3: Color(0x4DEBEBF5),
    labelInv: Color(0xFF000000),
    sep: Color(0x99545458),
    fill: Color(0x3D767680),
    fill2: Color(0x5C787880),
    fill3: Color(0xFF2C2C2E),
    gray2: Color(0xFF636366),
    gray3: Color(0xFF48484A),
    tint: Color(0xFFFF4D33),
    tintPress: Color(0xFFFF6A52),
    tintBg: Color(0x33FF4D33),
    tintInk: Color(0xFFFF9783),
    inverseBg: Color(0xFF2C2C2E),
    inverseFg: Color(0xFFFFFFFF),
    segSel: Color(0xFF636366),
    tabSel: Color(0x1FFFFFFF),
    glassBg: Color(0xF02C2C2E),
    glassEdge: Color(0x24FFFFFF),
    alertBg: Color(0xFA2C2C2E),
    glassShadow: [
      BoxShadow(color: Color(0x59000000), blurRadius: 6, offset: Offset(0, 2)),
      BoxShadow(color: Color(0x33000000), blurRadius: 16, offset: Offset(0, 6)),
    ],
  );
}

/// Type scale (SF Pro in the design; Inter is bundled as the closest open font).
class PassText {
  static const String family = 'Inter';
  static const String mono = 'monospace';

  static const TextStyle wordmark =
      TextStyle(fontFamily: family, fontSize: 64, height: 1, fontWeight: FontWeight.w800, letterSpacing: -1.28);
  static const TextStyle largeTitle =
      TextStyle(fontFamily: family, fontSize: 34, height: 41 / 34, fontWeight: FontWeight.w700, letterSpacing: 0.34);
  static const TextStyle display =
      TextStyle(fontFamily: family, fontSize: 36, height: 1, fontWeight: FontWeight.w600, letterSpacing: -1.08);
  static const TextStyle stat =
      TextStyle(fontFamily: family, fontSize: 40, height: 1, fontWeight: FontWeight.w700, letterSpacing: -1.2);
  static const TextStyle statUnit = TextStyle(fontFamily: family, fontSize: 18, fontWeight: FontWeight.w700);
  static const TextStyle title1 =
      TextStyle(fontFamily: family, fontSize: 28, height: 1.1, fontWeight: FontWeight.w700, letterSpacing: -0.56);
  static const TextStyle title2 = TextStyle(fontFamily: family, fontSize: 22, fontWeight: FontWeight.w700);
  static const TextStyle title3 = TextStyle(fontFamily: family, fontSize: 20, fontWeight: FontWeight.w700);
  static const TextStyle headline = TextStyle(fontFamily: family, fontSize: 17, fontWeight: FontWeight.w600);
  static const TextStyle body = TextStyle(fontFamily: family, fontSize: 17, fontWeight: FontWeight.w400);
  static const TextStyle callout = TextStyle(fontFamily: family, fontSize: 16, fontWeight: FontWeight.w400);
  static const TextStyle subhead = TextStyle(fontFamily: family, fontSize: 15, fontWeight: FontWeight.w400);
  static const TextStyle footnote = TextStyle(fontFamily: family, fontSize: 13, fontWeight: FontWeight.w400);
  static const TextStyle caption = TextStyle(fontFamily: family, fontSize: 12, fontWeight: FontWeight.w400);

  /// Uppercase table/section header: 12, +8% tracking. Apply `.toUpperCase()` to the text.
  static const TextStyle captionCaps =
      TextStyle(fontFamily: family, fontSize: 12, fontWeight: FontWeight.w400, letterSpacing: 0.96);
  static const TextStyle caption2 = TextStyle(fontFamily: family, fontSize: 11, fontWeight: FontWeight.w400);
  static const TextStyle tabLabel = TextStyle(fontFamily: family, fontSize: 10, fontWeight: FontWeight.w600);

  static const FontWeight regular = FontWeight.w400;
  static const FontWeight medium = FontWeight.w500;
  static const FontWeight semibold = FontWeight.w600;
  static const FontWeight bold = FontWeight.w700;
}

/// Spacing scale.
class PassSpace {
  static const double xxs = 2;
  static const double xs = 4;
  static const double s = 6;
  static const double sm = 8;
  static const double m = 10;
  static const double ml = 12;
  static const double l = 14;
  static const double card = 16; // card inner padding
  static const double lg = 18;
  static const double gutter = 20; // screen side padding
  static const double xl = 22;
  static const double xxl = 24;
  static const double xxxl = 32;
  static const double rowHeight = 52; // form/settings rows
  static const double navHeight = 56; // nav bar row incl. padding
  static const double tabBarHeight = 64;
  static const double tabBarBottom = 22;
  static const double contentBottom = 112; // space so the floating tab bar never covers content
  static const double glassButton = 44;
  static const double hairline = 0.5;

  /// Width at and above which the desktop layout (sidebar, master–detail) is used.
  static const double desktopBreakpoint = 900;
  static const double sidebarWidth = 260;
  static const double masterWidth = 420;
  static const double contentMaxWidth = 1100;
  static const double formMaxWidth = 640;
}

/// Corner radii.
class PassRadii {
  static const double card = 26; // grouped list cards
  static const double tile = 24; // stat tiles, wellness cards
  static const double notice = 22; // notice banners, court cards
  static const double hero = 28; // "Booked" hero, recovery card
  static const double bubble = 18;
  static const double chip = 16; // date/achievement/soreness tiles
  static const double slot = 14;
  static const double thumb = 8;
  static const double tag = 6; // amenity chips
  static const double alert = 34;
  static const double pill = 9999;
}

/// Motion.
class PassMotion {
  static const Duration fast = Duration(milliseconds: 150);
  static const Duration normal = Duration(milliseconds: 200);
  static const Duration swipe = Duration(milliseconds: 300);
  static const Curve swipeCurve = Cubic(.2, .8, .2, 1);

  /// iOS springs (SwiftUI `.smooth`, `.snappy`, `.bouncy`). Use with `spring.duration`.
  static final SpringCurve smooth = SpringCurve(response: .42, damping: 1);
  static final SpringCurve snappy = SpringCurve(response: .34, damping: .82);
  static final SpringCurve bouncy = SpringCurve(response: .4, damping: .66);
}

/// A spring (SwiftUI `.spring(response:dampingFraction:)`, mass 1) played as a Curve over [duration],
/// the time the spring needs to settle.
class SpringCurve extends Curve {
  SpringCurve({required double response, required double damping})
      : _sim = SpringSimulation(
            SpringDescription(
                mass: 1, stiffness: (2 * pi / response) * (2 * pi / response), damping: 4 * pi * damping / response),
            0,
            1,
            0) {
    const step = 1 / 240;
    var last = 0.0;
    for (var t = 0.0; t < 3; t += step) {
      if ((_sim.x(t) - 1).abs() > .01) last = t; // settled within 1%: the rest is invisible, and on the web every
      // animation frame redraws the whole screen
    }
    _end = last + step;
    duration = Duration(microseconds: (_end * 1e6).round());
  }

  final SpringSimulation _sim;
  late final double _end;
  late final Duration duration;

  @override
  double transformInternal(double t) => _sim.x(t * _end);
}

extension PassThemeX on BuildContext {
  /// Current palette: `context.c.tint`.
  PassColors get c => CupertinoTheme.brightnessOf(this) == Brightness.dark ? PassColors.dark : PassColors.light;

  /// True when the desktop layout applies.
  bool get isDesktop => MediaQuery.sizeOf(this).width >= PassSpace.desktopBreakpoint;
}
