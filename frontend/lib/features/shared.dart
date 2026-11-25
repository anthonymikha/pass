// Pieces several features use: the iOS calendar and compact date/time capsules, Notes-style tags, the free-slot
// run picker, and pass_v1's flow pieces (summary card, "Booked" hero, the glass action bar).
import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../theme/tokens.dart';
import '../widgets/controls.dart';
import '../widgets/layout.dart';
import '../widgets/loader.dart';
import '../widgets/svg_icon.dart';

Map<String, dynamic> asMap(Object? v) => v as Map<String, dynamic>;
List<Map<String, dynamic>> asMaps(Object? v) => (v as List<dynamic>? ?? const []).cast<Map<String, dynamic>>();

const _monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June', //
  'July', 'August', 'September', 'October', 'November', 'December',
];

DateTime _day(DateTime d) => DateTime(d.year, d.month, d.day);

/// The iOS inline calendar (UIDatePicker, inline style): month with arrows, weekday letters, a grid of days.
/// Days before [first], after [last] or refused by [isOpen] are greyed out and can't be picked.
class PassCalendar extends StatefulWidget {
  const PassCalendar(
      {super.key, required this.selected, required this.first, this.last, this.isOpen, required this.onChanged});
  final DateTime selected, first;
  final DateTime? last;
  final bool Function(DateTime day)? isOpen;
  final ValueChanged<DateTime> onChanged;

  @override
  State<PassCalendar> createState() => _PassCalendarState();
}

class _PassCalendarState extends State<PassCalendar> {
  late DateTime _month = DateTime(widget.selected.year, widget.selected.month);

  @override
  void didUpdateWidget(PassCalendar old) {
    super.didUpdateWidget(old);
    if (old.selected != widget.selected) _month = DateTime(widget.selected.year, widget.selected.month);
  }

  bool _canPick(DateTime d) =>
      !d.isBefore(_day(widget.first)) &&
      (widget.last == null || !d.isAfter(_day(widget.last!))) &&
      (widget.isOpen?.call(d) ?? true);

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final today = _day(DateTime.now());
    final canBack = _month.isAfter(DateTime(widget.first.year, widget.first.month));
    final canNext = widget.last == null || _month.isBefore(DateTime(widget.last!.year, widget.last!.month));
    Widget arrow(String icon, Size box, bool on, int step, String label) => Pressable(
          semanticLabel: label,
          onTap: on ? () => setState(() => _month = DateTime(_month.year, _month.month + step)) : null,
          child: SizedBox(
            width: PassSpace.glassButton,
            height: PassSpace.glassButton,
            child: Center(
                child: SvgIcon(icon, color: on ? c.tint : c.label3, viewBox: box, width: 11, height: 18, stroke: 2.5)),
          ),
        );
    final lead = DateTime(_month.year, _month.month, 1).weekday - 1; // Monday first
    final days = DateTime(_month.year, _month.month + 1, 0).day;
    final cells = <Widget>[
      for (var i = 0; i < lead; i++) const SizedBox.shrink(),
      for (var n = 1; n <= days; n++) _cell(context, DateTime(_month.year, _month.month, n), today),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        const SizedBox(width: PassSpace.sm),
        Expanded(
          child: Text('${_monthNames[_month.month - 1]} ${_month.year}',
              style: PassText.headline.copyWith(color: c.label)),
        ),
        arrow(PassIcons.back, const Size(12, 20), canBack, -1, 'Previous month'),
        arrow(PassIcons.chevronRight, const Size(8, 14), canNext, 1, 'Next month'),
      ]),
      const SizedBox(height: PassSpace.xs),
      Row(children: [
        for (final w in weekdays)
          Expanded(
            child: Text(w.substring(0, 3).toUpperCase(),
                textAlign: TextAlign.center,
                style: PassText.caption2.copyWith(fontWeight: PassText.semibold, color: c.label3)),
          ),
      ]),
      const SizedBox(height: PassSpace.xs),
      GridView.count(
        crossAxisCount: 7,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        padding: EdgeInsets.zero,
        children: cells,
      ),
    ]);
  }

  Widget _cell(BuildContext context, DateTime d, DateTime today) {
    final c = context.c;
    final on = _day(widget.selected) == d;
    final isToday = d == today;
    final can = _canPick(d);
    // iOS: the chosen day is a tinted disc, today is tint text (white on a full disc when chosen too).
    final (Color bg, Color fg) = on
        ? (isToday ? c.tint : c.tintBg, isToday ? PassColors.white : c.tint)
        : (PassColors.transparent, !can ? c.label3 : isToday ? c.tint : c.label);
    return Pressable(
      semanticLabel: dayLabel(d),
      onTap: can ? () => widget.onChanged(d) : null,
      child: Center(
        child: AnimatedContainer(
          duration: PassMotion.fast,
          width: 40,
          height: 40,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: bg, shape: BoxShape.circle),
          child: Text('${d.day}',
              style: PassText.title3.copyWith(
                  fontSize: 19, fontWeight: on || isToday ? PassText.semibold : PassText.regular, color: fg)),
        ),
      ),
    );
  }
}

/// A floating sheet (iOS 26: inset, rounded, over a dim backdrop) holding [child].
Future<T?> showPassSheet<T>(BuildContext context, Widget Function(BuildContext) child) =>
    showCupertinoModalPopup<T>(
      context: context,
      builder: (ctx) => SafeArea(
        top: false,
        child: Container(
          margin: const EdgeInsets.all(PassSpace.sm),
          padding: const EdgeInsets.all(PassSpace.ml),
          constraints: const BoxConstraints(maxWidth: PassSpace.formMaxWidth),
          decoration: BoxDecoration(
            color: ctx.c.alertBg,
            borderRadius: BorderRadius.circular(PassRadii.alert),
            boxShadow: ctx.c.glassShadow,
          ),
          child: child(ctx),
        ),
      ),
    );

/// Calendar in a sheet (what the iOS compact date picker opens); null when dismissed.
Future<DateTime?> pickDate(BuildContext context, {required DateTime value, required DateTime first, DateTime? last}) =>
    showPassSheet<DateTime>(
        context,
        (ctx) => PassCalendar(
            selected: value, first: first, last: last, onChanged: (d) => Navigator.of(ctx).pop(d)));

/// Time wheels in a sheet, 5-minute steps; the time of [value] changed (same day).
Future<DateTime?> pickTime(BuildContext context, DateTime value) async {
  var picked = value;
  final done = await showPassSheet<bool>(
    context,
    (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
      Align(
        alignment: Alignment.centerRight,
        child: PassLink('Done',
            padding: const EdgeInsets.all(PassSpace.sm), style: PassText.headline, onTap: () => Navigator.of(ctx).pop(true)),
      ),
      SizedBox(
        height: 216,
        child: CupertinoDatePicker(
          mode: CupertinoDatePickerMode.time,
          use24hFormat: true,
          minuteInterval: 5,
          initialDateTime: value.subtract(Duration(minutes: value.minute % 5)),
          onDateTimeChanged: (d) => picked = d,
        ),
      ),
    ]),
  );
  return done == true ? picked : null;
}

/// The iOS compact date picker's grey capsule ("Mon 30 Nov", "10:00").
class DateCapsule extends StatelessWidget {
  const DateCapsule(this.text, {super.key, required this.onTap, required this.semanticLabel});
  final String text, semanticLabel;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        semanticLabel: semanticLabel,
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: PassSpace.s),
          decoration: BoxDecoration(color: context.c.fill, borderRadius: BorderRadius.circular(PassRadii.thumb)),
          child: Text(text, style: PassText.body.copyWith(color: context.c.label)),
        ),
      );
}

/// Row with a label and the iOS compact date and time capsules: the date opens the calendar, the time the wheels.
class DateTimeRow extends StatelessWidget {
  const DateTimeRow(
      {super.key, required this.label, required this.value, required this.onChanged, this.timeOnly = false});
  final String label;
  final DateTime value;
  final ValueChanged<DateTime> onChanged;
  final bool timeOnly;

  @override
  Widget build(BuildContext context) => ListRow(
        label: label,
        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
          if (!timeOnly) ...[
            DateCapsule(dayLabel(value), semanticLabel: '$label date', onTap: () async {
              final today = _day(DateTime.now());
              final d = await pickDate(context, value: value, first: value.isBefore(today) ? _day(value) : today);
              if (d != null) onChanged(DateTime(d.year, d.month, d.day, value.hour, value.minute));
            }),
            const SizedBox(width: PassSpace.s),
          ],
          DateCapsule(hm(value), semanticLabel: '$label time', onTap: () async {
            final t = await pickTime(context, value);
            if (t != null) onChanged(DateTime(value.year, value.month, value.day, t.hour, t.minute));
          }),
        ]),
      );
}

/// The next whole hour from now, local: the default proposed start.
DateTime nextHour([int addHours = 1]) {
  final n = DateTime.now();
  return DateTime(n.year, n.month, n.day, n.hour + addHours);
}

/// Sport tags, as in Notes: tap a tag to select it, tap again to clear it; several can be on at once.
/// [all] adds an "All sports" tag that clears the selection; [single] keeps one tag on (a session has one sport).
class SportTags extends StatelessWidget {
  const SportTags(
      {super.key,
      required this.sports,
      required this.selected,
      required this.onChanged,
      this.all = false,
      this.single = false,
      this.padding = const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.ml, PassSpace.gutter, 0)});
  final List<Map<String, dynamic>> sports;
  final Set<int> selected;
  final ValueChanged<Set<int>> onChanged;
  final bool all, single;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    Widget tag(String label, bool on, VoidCallback onTap) => Pressable(
          semanticLabel: label,
          onTap: onTap,
          child: AnimatedContainer(
            duration: PassMotion.fast,
            padding: const EdgeInsets.symmetric(horizontal: PassSpace.l, vertical: PassSpace.sm),
            decoration: BoxDecoration(color: on ? c.tint : c.bgCard, borderRadius: BorderRadius.circular(PassRadii.pill)),
            child: Text(label,
                style: PassText.subhead.copyWith(
                    color: on ? PassColors.white : c.label, fontWeight: on ? PassText.semibold : PassText.regular)),
          ),
        );
    return Padding(
      padding: padding,
      child: Wrap(spacing: PassSpace.s, runSpacing: PassSpace.s, children: [
        if (all) tag('All sports', selected.isEmpty, () => onChanged({})),
        for (final s in sports)
          tag('${s['name']}', selected.contains(s['id']), () {
            final id = s['id'] as int;
            if (single) return onChanged({id});
            onChanged(selected.contains(id) ? ({...selected}..remove(id)) : {...selected, id});
          }),
      ]),
    );
  }
}

/// Sport names of a court's sport ids.
String sportNames(List<dynamic> ids, List<Map<String, dynamic>> sports) =>
    [for (final s in sports) if (ids.contains(s['id'])) '${s['name']}'].join(', ');

/// A run of consecutive free slots (BOOK-4), as the API sends them.
class SlotRun {
  const SlotRun(this.slots);
  final List<Map<String, dynamic>> slots;
  String get startsAt => slots.first['starts_at'] as String;
  String get endsAt => slots.last['ends_at'] as String;
  int get minutes => DateTime.parse(endsAt).difference(DateTime.parse(startsAt)).inMinutes;
}

/// Pick a day on the calendar (club time zone) and a run of consecutive free slots of one court (AVL-10, BOOK-4).
/// Tap a slot to start a run, tap a later slot to extend it; a gap starts a new run.
/// Days of the week in [openWeekdays] (0 = Monday, the court's price windows) are the only ones offered.
class SlotRunPicker extends StatefulWidget {
  const SlotRunPicker(
      {super.key,
      required this.courtId,
      required this.clubZone,
      required this.currency,
      required this.onChanged,
      this.openWeekdays});
  final int courtId;
  final String clubZone, currency;
  final ValueChanged<SlotRun?> onChanged;
  final Set<int>? openWeekdays;

  @override
  State<SlotRunPicker> createState() => SlotRunPickerState();
}

class SlotRunPickerState extends State<SlotRunPicker> {
  static const _days = 60;
  late final DateTime _today = clubToday(widget.clubZone);
  late DateTime _date = [
    for (var i = 0; i < _days; i++) DateTime(_today.year, _today.month, _today.day + i),
  ].firstWhere(_open, orElse: () => _today);
  int? _from, _to;
  int _reload = 0;

  bool _open(DateTime d) => widget.openWeekdays?.contains(d.weekday - 1) ?? true;

  /// After a `slot_taken`: forget the run and load the day again.
  void reload() => setState(() {
        _reload++;
        _from = _to = null;
        widget.onChanged(null);
      });

  void _pick(List<Map<String, dynamic>> slots, int i) {
    bool joined(int k) => slots[k]['ends_at'] == slots[k + 1]['starts_at'];
    setState(() {
      if (_from != null && i > _to! && [for (var k = _to!; k < i; k++) joined(k)].every((x) => x)) {
        _to = i;
      } else {
        _from = _to = i;
      }
    });
    widget.onChanged(SlotRun(slots.sublist(_from!, _to! + 1)));
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PassCard(
        padding: const EdgeInsets.all(PassSpace.ml),
        child: PassCalendar(
            selected: _date,
            first: _today,
            last: _today.add(const Duration(days: _days)),
            isOpen: _open,
            onChanged: (d) {
              setState(() {
                _date = d;
                _from = _to = null;
              });
              widget.onChanged(null);
            }),
      ),
      CapsHeader('Free times · ${dayLabel(_date)}'),
      ApiLoader<List<dynamic>>(
        key: ValueKey('slots-${widget.courtId}-${ymd(_date)}-$_reload'),
        load: () async =>
            await ApiClient.instance.get('/api/courts/${widget.courtId}/slots/', query: {'date': ymd(_date)}) as List,
        builder: (context, data, _) {
          final slots = asMaps(data);
          if (slots.isEmpty) return const EmptyText('No free times on this day.');
          // pass_v1's slot grid: four to a row.
          return Padding(
            padding: kGutter,
            child: GridView.count(
              crossAxisCount: 4,
              mainAxisSpacing: PassSpace.s,
              crossAxisSpacing: PassSpace.s,
              childAspectRatio: 1.5,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              padding: EdgeInsets.zero,
              children: [
                for (var i = 0; i < slots.length; i++)
                  Pressable(
                    semanticLabel: 'Slot ${hm(at(slots[i]['starts_at'] as String, widget.clubZone))}',
                    onTap: () => _pick(slots, i),
                    child: Builder(builder: (context) {
                      final on = _from != null && i >= _from! && i <= _to!;
                      return AnimatedContainer(
                        duration: PassMotion.fast,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                            color: on ? c.tint : c.bgCard, borderRadius: BorderRadius.circular(PassRadii.slot)),
                        child: Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(hm(at(slots[i]['starts_at'] as String, widget.clubZone)),
                              style: PassText.subhead
                                  .copyWith(color: on ? PassColors.white : c.label, fontWeight: PassText.semibold)),
                          Text(money(slots[i]['price'] as String?, widget.currency),
                              style: PassText.caption2.copyWith(color: on ? PassColors.white : c.label2)),
                        ]),
                      );
                    }),
                  ),
              ],
            ),
          );
        },
      ),
      const FootnoteText('Tap a start time, then a later one for a longer booking.'),
    ]);
  }
}

/// pass_v1's summary card: label column and semibold values.
class SummaryCard extends StatelessWidget {
  const SummaryCard({super.key, required this.rows, this.labelWidth = 90});
  final List<(String, String)> rows;
  final double labelWidth;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GroupedCard(
      margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.card, PassSpace.gutter, 0),
      children: [
        for (final (label, value) in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: PassSpace.m),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: labelWidth, child: Text(label, style: PassText.callout.copyWith(color: c.label2))),
              Expanded(
                  child: Text(value, style: PassText.callout.copyWith(fontWeight: PassText.semibold, color: c.label))),
            ]),
          ),
      ],
    );
  }
}

/// pass_v1's tint "Booked" hero with the follow-up actions.
class BookedBody extends StatelessWidget {
  const BookedBody(
      {super.key, required this.kicker, required this.headline, required this.body, required this.sessionId, required this.againPath});
  final String kicker, headline, body, againPath;
  final int sessionId;

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.ml, PassSpace.gutter, 0),
          padding: const EdgeInsets.fromLTRB(PassSpace.gutter, 28, PassSpace.gutter, PassSpace.xxl),
          decoration: BoxDecoration(color: context.c.tint, borderRadius: BorderRadius.circular(PassRadii.hero)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(kicker.toUpperCase(), style: PassText.caption.copyWith(letterSpacing: 1.2, color: PassColors.white)),
            const SizedBox(height: PassSpace.m),
            Text(headline, style: PassText.display.copyWith(color: PassColors.white, height: 1.1)),
            const SizedBox(height: PassSpace.l),
            Text(body, style: PassText.subhead.copyWith(color: PassColors.white)),
          ]),
        ),
        const SizedBox(height: PassSpace.lg),
        PassButton('See session', kind: PassButtonKind.secondary, onPressed: () => context.go('/sessions/$sessionId')),
        Padding(
          padding: kGutter,
          child: Align(
            alignment: Alignment.centerLeft,
            child: PassLink('Book another',
                padding: const EdgeInsets.symmetric(vertical: PassSpace.ml), onTap: () => context.go(againPath)),
          ),
        ),
      ]);
}

/// Primary pill button with the design's flow margin (18 20 20).
const flowButtonMargin = EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.lg, PassSpace.gutter, PassSpace.gutter);

/// Glass bar pinned under a listing (Airbnb's reserve bar): a price or summary on the left, one action on the right.
class ActionBar extends StatelessWidget {
  const ActionBar(
      {super.key, required this.title, this.subtitle, required this.action, this.onPressed, this.enabled = true, this.busy = false});
  final String title, action;
  final String? subtitle;
  final VoidCallback? onPressed;
  final bool enabled, busy;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final active = enabled && !busy && onPressed != null;
    return Padding(
      padding: const EdgeInsets.fromLTRB(PassSpace.ml, PassSpace.sm, PassSpace.ml, PassSpace.sm),
      child: Glass(
        radius: PassRadii.card,
        padding: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.m, PassSpace.m, PassSpace.m),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: PassText.headline.copyWith(color: c.label)),
              if (subtitle != null)
                Text(subtitle!, maxLines: 1, overflow: TextOverflow.ellipsis, style: PassText.footnote.copyWith(color: c.label2)),
            ]),
          ),
          const SizedBox(width: PassSpace.ml),
          Opacity(
            opacity: enabled ? 1 : .4,
            child: Pressable(
              onTap: active ? onPressed : null,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 13, horizontal: PassSpace.xl),
                decoration: BoxDecoration(color: c.tint, borderRadius: BorderRadius.circular(PassRadii.pill)),
                child: busy
                    ? const CupertinoActivityIndicator(color: PassColors.white, radius: 10)
                    : Text(action, style: PassText.headline.copyWith(color: PassColors.white)),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}

/// A day with arrows either side and the date capsule between (opens the calendar): the club schedule's day.
class DayBar extends StatelessWidget {
  const DayBar({super.key, required this.value, required this.first, required this.last, required this.onChanged});
  final DateTime value, first, last;
  final ValueChanged<DateTime> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    Widget arrow(String icon, Size box, int step, String label) {
      final d = DateTime(value.year, value.month, value.day + step);
      final on = !d.isBefore(first) && !d.isAfter(last);
      return Pressable(
        semanticLabel: label,
        onTap: on ? () => onChanged(d) : null,
        child: SizedBox(
          width: PassSpace.glassButton,
          height: PassSpace.glassButton,
          child: Center(child: SvgIcon(icon, color: on ? c.tint : c.label3, viewBox: box, width: 11, height: 18, stroke: 2.5)),
        ),
      );
    }

    return Padding(
      padding: kGutter,
      child: Row(children: [
        arrow(PassIcons.back, const Size(12, 20), -1, 'Previous day'),
        Expanded(
          child: Center(
            child: DateCapsule(dayLabel(value), semanticLabel: 'Pick a day', onTap: () async {
              final d = await pickDate(context, value: value, first: first, last: last);
              if (d != null) onChanged(d);
            }),
          ),
        ),
        arrow(PassIcons.chevronRight, const Size(8, 14), 1, 'Next day'),
      ]),
    );
  }
}
