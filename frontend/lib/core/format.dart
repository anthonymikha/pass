// Times, dates and money as the screens show them.
// Court times are in the club's time zone, everything else in the device's (mvp.md, Screens). The API sends UTC.
import 'package:timezone/data/latest_10y.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

bool _tzReady = false;

tz.Location zone(String name) {
  if (!_tzReady) {
    tzdata.initializeTimeZones();
    _tzReady = true;
  }
  return tz.getLocation(name);
}

/// Every IANA zone name, for the time zone pickers.
List<String> zoneNames() {
  zone('UTC');
  return tz.timeZoneDatabase.locations.keys.toList()..sort();
}

/// An instant from the API, in the club's time zone (null: the device's).
DateTime at(String iso, [String? clubZone]) {
  final utc = DateTime.parse(iso).toUtc();
  return clubZone == null ? utc.toLocal() : tz.TZDateTime.from(utc, zone(clubZone));
}

/// Wall-clock [day] at [hour]:[minute] in [clubZone], as an instant.
DateTime clubDateTime(String clubZone, DateTime day, [int hour = 0, int minute = 0]) =>
    tz.TZDateTime(zone(clubZone), day.year, day.month, day.day, hour, minute);

/// Today's date in [clubZone] (GEN-9).
DateTime clubToday(String clubZone) {
  final now = tz.TZDateTime.now(zone(clubZone));
  return DateTime(now.year, now.month, now.day);
}

/// ISO 8601 with an offset, as the API wants it (GEN-7).
String iso(DateTime t) => t.toUtc().toIso8601String();

/// `YYYY-MM-DD`.
String ymd(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "16:05".
String hm(DateTime t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

/// "Tue 25 Nov".
String dayLabel(DateTime t) => '${weekdays[t.weekday - 1].substring(0, 3)} ${t.day} ${_months[t.month - 1]}';

/// "Today · Tue 25 Nov" (also Tomorrow and Yesterday), else "Tue 25 Nov". Both are dates (no time of day).
String relativeDay(DateTime day, DateTime today) {
  DateTime shift(int n) => DateTime(today.year, today.month, today.day + n);
  final word = day == today ? 'Today' : day == shift(1) ? 'Tomorrow' : day == shift(-1) ? 'Yesterday' : null;
  return word == null ? dayLabel(day) : '$word · ${dayLabel(day)}';
}

/// "Tue 25 Nov · 16:00–17:30".
String timeRange(DateTime start, DateTime end) => '${dayLabel(start)} · ${hm(start)}–${hm(end)}';

/// "09:00:00" from the API to "09:00".
String clock(String apiTime) => apiTime.length >= 5 ? apiTime.substring(0, 5) : apiTime;

/// A court's price windows as a price list: days in a row with the same windows share a line,
/// ("Mon–Fri", ["08:00–22:00 · 20.00 USD"]), all seven are "Every day". Days without a window are left out.
List<(String, List<String>)> priceLines(List<Map<String, dynamic>> rates, String currency) {
  List<String> windows(int day) => [
        for (final r in rates.where((r) => r['weekday'] == day).toList()
          ..sort((a, b) => '${a['start_time']}'.compareTo('${b['start_time']}')))
          '${clock('${r['start_time']}')}–${clock('${r['end_time']}')} · ${money('${r['price']}', currency)}',
      ];
  final lines = <(String, List<String>)>[];
  for (var d = 0; d < 7;) {
    final w = windows(d);
    var e = d;
    while (e < 6 && windows(e + 1).join('|') == w.join('|')) {
      e++;
    }
    if (w.isNotEmpty) {
      lines.add((
        e == d ? weekdays[d] : e - d == 6 ? 'Every day' : '${weekdays[d].substring(0, 3)}–${weekdays[e].substring(0, 3)}',
        w,
      ));
    }
    d = e + 1;
  }
  return lines;
}

/// Minor units per currency (GEN-15). The MVP shows USD only (FE-3).
int minorUnits(String currency) => switch (currency) {
      'BIF' || 'CLP' || 'DJF' || 'GNF' || 'ISK' || 'JPY' || 'KMF' || 'KRW' || 'LBP' || 'PYG' || 'RWF' || 'UGX' ||
      'UYI' || 'VND' || 'VUV' || 'XAF' || 'XOF' || 'XPF' =>
        0,
      'BHD' || 'IQD' || 'JOD' || 'KWD' || 'LYD' || 'OMR' || 'TND' => 3,
      _ => 2,
    };

/// "50.000", "USD" -> "50.00 USD": the API's three stored decimals cut to the currency's minor units (GEN-13).
/// The digits are not recomputed.
String money(String? amount, String? currency) {
  if (amount == null || currency == null || currency.isEmpty) return '';
  final dot = amount.indexOf('.');
  final units = minorUnits(currency);
  final shown = dot < 0
      ? amount
      : units == 0
          ? amount.substring(0, dot)
          : amount.substring(0, (dot + 1 + units).clamp(0, amount.length));
  return '$shown $currency';
}

/// FE-4: coach rate (per hour, a decimal string) times the minutes, rounded to the currency's minor units,
/// half away from zero (GEN-16). Exact: done in thousandths.
String coachFee(String rate, int minutes, String currency) {
  final thousandths = _thousandths(rate);
  final step = [1000, 100, 10, 1][minorUnits(currency)];
  final raw = thousandths * minutes;
  final rounded = ((raw + 30 * step) ~/ (60 * step)) * step; // round half up over minutes/60
  final whole = rounded ~/ 1000;
  final frac = (rounded % 1000).toString().padLeft(3, '0');
  final units = minorUnits(currency);
  return units == 0 ? '$whole' : '$whole.${frac.substring(0, units)}';
}

/// "50.000" -> 50000: a non-negative API decimal in thousandths, its stored precision.
int _thousandths(String amount) {
  final parts = amount.split('.');
  return int.parse(parts[0]) * 1000 + int.parse('${parts.length > 1 ? parts[1] : ''}000'.substring(0, 3));
}

/// Quoted amounts added up exactly, in thousandths: the total of several bookings made together ("60.000").
String sumMoney(Iterable<String> amounts) {
  final t = amounts.fold(0, (sum, a) => sum + _thousandths(a));
  return '${t ~/ 1000}.${(t % 1000).toString().padLeft(3, '0')}';
}
