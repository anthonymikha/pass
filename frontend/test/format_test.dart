import 'package:flutter_test/flutter_test.dart';
import 'package:pass_app/core/format.dart';

Map<String, dynamic> _rate(int day, String from, String to, String price) =>
    {'weekday': day, 'start_time': '$from:00', 'end_time': '$to:00', 'price': price};

/// Lines as text: records holding lists don't compare by value.
List<String> _lines(List<Map<String, dynamic>> rates) => [for (final (d, w) in priceLines(rates, 'USD')) '$d: ${w.join(' / ')}'];

void main() {
  test('price windows: days in a row with the same windows share a line', () {
    final weekdaysOnly = [for (var d = 0; d < 5; d++) _rate(d, '08:00', '22:00', '20.000')];
    expect(_lines(weekdaysOnly), ['Mon–Fri: 08:00–22:00 · 20.00 USD']);

    final week = [
      for (var d = 0; d < 7; d++) _rate(d, '08:00', '22:00', '20.000'),
    ];
    expect(_lines(week), ['Every day: 08:00–22:00 · 20.00 USD']);

    final mixed = [
      _rate(0, '16:00', '22:00', '30.000'),
      _rate(0, '08:00', '16:00', '20.000'), // windows come in any order
      _rate(1, '08:00', '16:00', '20.000'),
      _rate(1, '16:00', '22:00', '30.000'),
      _rate(3, '08:00', '22:00', '25.000'), // Wednesday has none
      _rate(6, '10:00', '18:00', '25.000'),
    ];
    expect(_lines(mixed), [
      'Mon–Tue: 08:00–16:00 · 20.00 USD / 16:00–22:00 · 30.00 USD',
      'Thursday: 08:00–22:00 · 25.00 USD',
      'Sunday: 10:00–18:00 · 25.00 USD',
    ]);
  });

  test('a day near today says so', () {
    final today = DateTime(2026, 11, 25);
    expect(relativeDay(today, today), 'Today · Wed 25 Nov');
    expect(relativeDay(DateTime(2026, 11, 26), today), 'Tomorrow · Thu 26 Nov');
    expect(relativeDay(DateTime(2026, 11, 24), today), 'Yesterday · Tue 24 Nov');
    expect(relativeDay(DateTime(2026, 11, 28), today), 'Sat 28 Nov');
  });
}
