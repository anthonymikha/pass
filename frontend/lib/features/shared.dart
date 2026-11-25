// Pieces several features use: day chips, the free-slot run picker, date and time rows.
import 'package:flutter/cupertino.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../theme/tokens.dart';
import '../widgets/controls.dart';
import '../widgets/layout.dart';
import '../widgets/loader.dart';
import '../widgets/svg_icon.dart';

Map<String, dynamic> asMap(Object? v) => v as Map<String, dynamic>;
List<Map<String, dynamic>> asMaps(Object? v) => (v as List<dynamic>? ?? const []).cast<Map<String, dynamic>>();

/// Horizontal row of day chips: [first] and the next [count - 1] days.
class DayChips extends StatelessWidget {
  const DayChips({super.key, required this.first, required this.selected, required this.onChanged, this.count = 61});
  final DateTime first, selected;
  final ValueChanged<DateTime> onChanged;
  final int count;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return SizedBox(
      height: 64,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: PassSpace.gutter),
        itemCount: count,
        separatorBuilder: (_, __) => const SizedBox(width: PassSpace.s),
        itemBuilder: (context, i) {
          final d = DateTime(first.year, first.month, first.day + i);
          final on = ymd(d) == ymd(selected);
          return Pressable(
            semanticLabel: dayLabel(d),
            onTap: () => onChanged(d),
            child: Container(
              width: 52,
              decoration: BoxDecoration(
                  color: on ? c.tint : c.bgCard, borderRadius: BorderRadius.circular(PassRadii.chip)),
              child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                Text(weekdays[d.weekday - 1].substring(0, 3),
                    style: PassText.caption.copyWith(color: on ? PassColors.white : c.label2)),
                Text('${d.day}',
                    style: PassText.headline.copyWith(color: on ? PassColors.white : c.label)),
              ]),
            ),
          );
        },
      ),
    );
  }
}

/// A run of consecutive free slots (BOOK-4), as the API sends them.
class SlotRun {
  const SlotRun(this.slots);
  final List<Map<String, dynamic>> slots;
  String get startsAt => slots.first['starts_at'] as String;
  String get endsAt => slots.last['ends_at'] as String;
  int get minutes => DateTime.parse(endsAt).difference(DateTime.parse(startsAt)).inMinutes;
}

/// Pick a date (club time zone) and a run of consecutive free slots of one court (AVL-10, BOOK-4).
/// Tap a slot to start a run, tap a later slot to extend it; a gap starts a new run.
class SlotRunPicker extends StatefulWidget {
  const SlotRunPicker(
      {super.key, required this.courtId, required this.clubZone, required this.currency, required this.onChanged});
  final int courtId;
  final String clubZone, currency;
  final ValueChanged<SlotRun?> onChanged;

  @override
  State<SlotRunPicker> createState() => SlotRunPickerState();
}

class SlotRunPickerState extends State<SlotRunPicker> {
  late final DateTime _today = clubToday(widget.clubZone);
  late DateTime _date = _today;
  int? _from, _to;
  int _reload = 0;

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
      DayChips(
          first: _today,
          selected: _date,
          onChanged: (d) {
            setState(() {
              _date = d;
              _from = _to = null;
            });
            widget.onChanged(null);
          }),
      const SizedBox(height: PassSpace.ml),
      ApiLoader<List<dynamic>>(
        key: ValueKey('slots-${widget.courtId}-${ymd(_date)}-$_reload'),
        load: () async =>
            await ApiClient.instance.get('/api/courts/${widget.courtId}/slots/', query: {'date': ymd(_date)}) as List,
        builder: (context, data, _) {
          final slots = asMaps(data);
          if (slots.isEmpty) return const EmptyText('No free times on this day.');
          return Padding(
            padding: kGutter,
            child: Wrap(spacing: PassSpace.s, runSpacing: PassSpace.s, children: [
              for (var i = 0; i < slots.length; i++)
                Pressable(
                  semanticLabel: 'Slot ${hm(at(slots[i]['starts_at'] as String, widget.clubZone))}',
                  onTap: () => _pick(slots, i),
                  child: Builder(builder: (context) {
                    final on = _from != null && i >= _from! && i <= _to!;
                    return Container(
                      width: 84,
                      padding: const EdgeInsets.symmetric(vertical: PassSpace.sm),
                      decoration: BoxDecoration(
                          color: on ? c.tint : c.bgCard, borderRadius: BorderRadius.circular(PassRadii.slot)),
                      child: Column(children: [
                        Text(hm(at(slots[i]['starts_at'] as String, widget.clubZone)),
                            style: PassText.subhead
                                .copyWith(color: on ? PassColors.white : c.label, fontWeight: PassText.semibold)),
                        Text(money(slots[i]['price'] as String?, widget.currency),
                            style: PassText.caption2.copyWith(color: on ? PassColors.white : c.label2)),
                      ]),
                    );
                  }),
                ),
            ]),
          );
        },
      ),
    ]);
  }
}

/// Row with a date and time that opens a Cupertino date picker (5-minute steps).
class DateTimeRow extends StatelessWidget {
  const DateTimeRow(
      {super.key, required this.label, required this.value, required this.onChanged, this.mode = CupertinoDatePickerMode.dateAndTime});
  final String label;
  final DateTime value;
  final ValueChanged<DateTime> onChanged;
  final CupertinoDatePickerMode mode;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final text = mode == CupertinoDatePickerMode.time ? hm(value) : '${dayLabel(value)} · ${hm(value)}';
    return ListRow(
      label: label,
      onTap: () => _pick(context),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        Text(text, style: PassText.body.copyWith(color: c.label2)),
        const SizedBox(width: PassSpace.s),
        SvgIcon(PassIcons.updown, color: c.label2, viewBox: const Size(10, 16), width: 10, height: 16, stroke: 1.8),
      ]),
    );
  }

  Future<void> _pick(BuildContext context) async {
    var picked = value;
    await showCupertinoModalPopup<void>(
      context: context,
      builder: (ctx) => Container(
        height: 300,
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
              child: CupertinoDatePicker(
                mode: mode,
                use24hFormat: true,
                minuteInterval: 5,
                initialDateTime: value,
                onDateTimeChanged: (d) => picked = d,
              ),
            ),
          ]),
        ),
      ),
    );
    if (picked != value) onChanged(picked);
  }
}

/// The next whole hour from now, local: the default proposed start.
DateTime nextHour([int addHours = 1]) {
  final n = DateTime.now();
  return DateTime(n.year, n.month, n.day, n.hour + addHours);
}
