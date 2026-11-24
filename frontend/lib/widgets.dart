import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import 'api.dart';

/// Loads data once, shows a spinner, an error with a retry, or the content. `reload` loads again.
class Loaded<T> extends StatefulWidget {
  const Loaded({super.key, required this.load, required this.builder});
  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, VoidCallback reload) builder;

  @override
  State<Loaded<T>> createState() => _LoadedState<T>();
}

class _LoadedState<T> extends State<Loaded<T>> {
  late Future<T> _future = widget.load();

  void _reload() => setState(() => _future = widget.load());

  @override
  void didUpdateWidget(Loaded<T> old) {
    super.didUpdateWidget(old);
    if (old.load != widget.load) _future = widget.load();
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<T>(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text('${snap.error}', textAlign: TextAlign.center),
                  const SizedBox(height: 12),
                  OutlinedButton(onPressed: _reload, child: const Text('Try again')),
                ]),
              ),
            );
          }
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          return widget.builder(context, snap.data as T, _reload);
        },
      );
}

/// Runs an API action; shows its error (or `done`) in a snackbar. True when it worked.
Future<bool> act(BuildContext context, Future<void> Function() action, {String? done}) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    await action();
    if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
    return true;
  } catch (e) {
    messenger.showSnackBar(SnackBar(content: Text('$e')));
    return false;
  }
}

Future<bool> confirm(BuildContext context, String question) async =>
    await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        content: Text(question),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('No')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Yes')),
        ],
      ),
    ) ??
    false;

/// Page body with a readable width on the web.
class Body extends StatelessWidget {
  const Body({super.key, required this.children, this.maxWidth = 720});
  final List<Widget> children;
  final double maxWidth;

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth),
          child: ListView(padding: const EdgeInsets.all(16), children: children),
        ),
      );
}

class Heading extends StatelessWidget {
  const Heading(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 8),
        child: Text(text, style: Theme.of(context).textTheme.titleMedium),
      );
}

class TimezoneField extends StatelessWidget {
  const TimezoneField({super.key, required this.initial, required this.onChanged});
  final String initial;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => Autocomplete<String>(
        initialValue: TextEditingValue(text: initial),
        optionsBuilder: (v) => timezones().where((z) => z.toLowerCase().contains(v.text.toLowerCase())).take(30),
        onSelected: onChanged,
        fieldViewBuilder: (context, controller, focus, submit) => TextField(
          controller: controller,
          focusNode: focus,
          decoration: const InputDecoration(labelText: 'Timezone', hintText: 'Asia/Beirut'),
          onChanged: onChanged,
        ),
      );
}

/// Pick a date and a run of free, back-to-back slots of one court (AVL-10, BOOK-4).
/// Reports the run, or null when nothing is picked.
class SlotPicker extends StatefulWidget {
  const SlotPicker({super.key, required this.detail, required this.onChanged, this.initialDate});
  final Map<String, dynamic> detail; // court detail (CLUB-31)
  final void Function(String? startsAt, String? endsAt, String price) onChanged;
  final DateTime? initialDate;

  @override
  State<SlotPicker> createState() => _SlotPickerState();
}

class _SlotPickerState extends State<SlotPicker> {
  late final String zone = widget.detail['club']['timezone'] as String;
  late final DateTime today = _today();
  late DateTime date = widget.initialDate != null && !widget.initialDate!.isBefore(today) ? widget.initialDate! : today;
  int? a, b; // picked run of slots, both included

  DateTime _today() {
    final now = tz.TZDateTime.now(tz.getLocation(zone));
    return DateTime(now.year, now.month, now.day);
  }

  Future<List<Map<String, dynamic>>> _load() =>
      Api.instance.rows('courts/${widget.detail['court']['id']}/slots/', {'date': isoDate(date)});

  late Future<List<Map<String, dynamic>>> slots = _load();

  void _setDate(DateTime d) {
    setState(() {
      date = d;
      a = b = null;
      slots = _load();
    });
    widget.onChanged(null, null, '0');
  }

  void _tap(List<Map<String, dynamic>> s, int i) {
    setState(() {
      if (a == null || (a == i && b == i)) {
        a = b = a == null ? i : null;
      } else {
        final lo = i < a! ? i : a!, hi = i > b! ? i : b!;
        var joined = true;
        for (var k = lo; k < hi; k++) {
          if (s[k]['ends_at'] != s[k + 1]['starts_at']) joined = false;
        }
        a = joined ? lo : i;
        b = joined ? hi : i;
      }
    });
    if (a == null) return widget.onChanged(null, null, '0');
    final price = s.sublist(a!, b! + 1).fold<num>(0, (t, x) => t + num.parse('${x['price']}'));
    widget.onChanged(s[a!]['starts_at'] as String, s[b!]['ends_at'] as String, '$price');
  }

  @override
  Widget build(BuildContext context) {
    final last = today.add(const Duration(days: 60)); // AVL-5
    final currency = widget.detail['club']['currency'] as String;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        IconButton(
          onPressed: date.isAfter(today) ? () => _setDate(date.subtract(const Duration(days: 1))) : null,
          icon: const Icon(Icons.chevron_left),
          tooltip: 'Previous day',
        ),
        TextButton.icon(
          icon: const Icon(Icons.calendar_today, size: 18),
          label: Text(day(date)),
          onPressed: () async {
            final d = await showDatePicker(context: context, initialDate: date, firstDate: today, lastDate: last);
            if (d != null) _setDate(d);
          },
        ),
        IconButton(
          onPressed: date.isBefore(last) ? () => _setDate(date.add(const Duration(days: 1))) : null,
          icon: const Icon(Icons.chevron_right),
          tooltip: 'Next day',
        ),
      ]),
      Text('Times in $zone. Tap a first and a last slot to book several in a row.',
          style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 8),
      FutureBuilder(
        future: slots,
        builder: (context, snap) {
          if (snap.hasError) return Text('${snap.error}');
          if (!snap.hasData) return const LinearProgressIndicator();
          final s = snap.data!;
          if (s.isEmpty) return const Text('No free slots on this day.');
          return Wrap(spacing: 8, runSpacing: 8, children: [
            for (var i = 0; i < s.length; i++)
              FilterChip(
                selected: a != null && i >= a! && i <= b!,
                label: Text('${hm(inZone(s[i]['starts_at'], zone))}–${hm(inZone(s[i]['ends_at'], zone))}'
                    '  ${money(s[i]['price'], currency)}'),
                onSelected: (_) => _tap(s, i),
              ),
          ]);
        },
      ),
    ]);
  }
}
