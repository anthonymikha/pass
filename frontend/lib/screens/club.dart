import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:timezone/timezone.dart' as tz;

import '../api.dart';
import '../widgets.dart';
import 'player.dart' show sports;
import 'sessions.dart' show StatusChip;

/// My clubs (CLUB-33) and creating one (CLUB-1, base USD: FE-3).
class ClubsScreen extends StatelessWidget {
  const ClubsScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('My clubs')),
        body: Loaded(
          load: () => Api.instance.rows('me/clubs/'),
          builder: (context, clubs, reload) => Body(children: [
            if (clubs.isEmpty)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Text('You do not run a club. Create one to list your courts, prices, amenities and rentables.',
                    textAlign: TextAlign.center),
              ),
            for (final c in clubs)
              Card(
                child: ListTile(
                  title: Text(c['name']),
                  subtitle: Text((c['roles'] as List).join(', ')),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.go('/clubs/${c['id']}'),
                ),
              ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Create a club'),
              onPressed: () async {
                final club = await _clubDialog(context, {'timezone': Api.instance.me?['timezone'] ?? 'UTC'});
                if (club != null && context.mounted) context.go('/clubs/${club['id']}');
              },
            ),
          ]),
        ),
      );
}

/// Create (no `id`) or edit a club's name, address and timezone. Returns the saved club.
Future<Map?> _clubDialog(BuildContext context, Map club) {
  final name = TextEditingController(text: club['name']), address = TextEditingController(text: club['address']);
  var zone = club['timezone'] as String;
  return showDialog<Map>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(club['id'] == null ? 'New club' : 'Club details'),
      content: SizedBox(
        width: 400,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: name, decoration: const InputDecoration(labelText: 'Name')),
          TextField(controller: address, decoration: const InputDecoration(labelText: 'Address')),
          TimezoneField(initial: zone, onChanged: (v) => zone = v),
          if (club['id'] == null)
            const Padding(padding: EdgeInsets.only(top: 12), child: Text('Prices are in USD.')),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
        FilledButton(
          onPressed: () async {
            final body = {'name': name.text.trim(), 'address': address.text.trim(), 'timezone': zone.trim()};
            Map? saved;
            final ok = await act(
                c,
                () async => saved = club['id'] == null
                    ? await Api.instance.post('clubs/', {...body, 'currency': 'USD'})
                    : await Api.instance.patch('clubs/${club['id']}/', body));
            if (ok && c.mounted) Navigator.pop(c, saved);
          },
          child: const Text('Save'),
        ),
      ],
    ),
  );
}

/// One club for its club side: the owner gets every tab, staff the schedule only (ACC-5, ACC-6).
class ClubScreen extends StatelessWidget {
  const ClubScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => Material(
        child: Loaded(
        load: () async {
          final mine = await Api.instance.rows('me/clubs/');
          return mine.firstWhere((c) => c['id'] == id, orElse: () => throw ApiError(404, 'Not your club.'));
        },
        builder: (context, club, reload) {
          final owner = (club['roles'] as List).contains('owner');
          final tabs = {
            'Schedule': _Schedule(club),
            if (owner) 'Courts and prices': _Courts(club),
            if (owner) 'Amenities and rentables': _Equipment(club),
            if (owner) 'Staff': _Staff(club),
          };
          return DefaultTabController(
            length: tabs.length,
            child: Scaffold(
              appBar: AppBar(
                title: Text(club['name']),
                actions: [
                  if (owner)
                    IconButton(
                      icon: const Icon(Icons.edit),
                      tooltip: 'Club details',
                      onPressed: () async {
                        if (await _clubDialog(context, club) != null) reload();
                      },
                    ),
                ],
                bottom: TabBar(isScrollable: true, tabs: [for (final t in tabs.keys) Tab(text: t)]),
              ),
              body: TabBarView(children: tabs.values.toList()),
            ),
          );
        },
      ),
      );
}

/// RPT-1: sessions on the club's courts, a day or a week, with rental decisions (BOOK-40) and cancel (BOOK-50).
class _Schedule extends StatefulWidget {
  const _Schedule(this.club);
  final Map club;

  @override
  State<_Schedule> createState() => _ScheduleState();
}

class _ScheduleState extends State<_Schedule> {
  late final String zone = widget.club['timezone'];
  late DateTime from = _today();
  int days = 1;

  DateTime _today() {
    final n = tz.TZDateTime.now(tz.getLocation(zone));
    return DateTime(n.year, n.month, n.day);
  }

  Future<Map> _load() async => await Api.instance.get('clubs/${widget.club['id']}/schedule/', {
        'from': isoDate(from),
        'to': isoDate(from.add(Duration(days: days - 1))),
      }) as Map;

  @override
  Widget build(BuildContext context) {
    final owner = (widget.club['roles'] as List).contains('owner');
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(8),
        child: Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          IconButton(
              icon: const Icon(Icons.chevron_left),
              tooltip: 'Earlier',
              onPressed: () => setState(() => from = from.subtract(Duration(days: days)))),
          TextButton(
            onPressed: () async {
              final d = await showDatePicker(
                  context: context, initialDate: from, firstDate: DateTime(2020), lastDate: DateTime(2100));
              if (d != null) setState(() => from = d);
            },
            child: Text(days == 1 ? day(from) : '${day(from)} – ${day(from.add(Duration(days: days - 1)))}'),
          ),
          IconButton(
              icon: const Icon(Icons.chevron_right),
              tooltip: 'Later',
              onPressed: () => setState(() => from = from.add(Duration(days: days)))),
          SegmentedButton<int>(
            segments: const [ButtonSegment(value: 1, label: Text('Day')), ButtonSegment(value: 7, label: Text('Week'))],
            selected: {days},
            onSelectionChanged: (v) => setState(() => days = v.first),
          ),
        ]),
      ),
      Expanded(
        child: Loaded(
          key: ValueKey('$from$days'),
          load: _load,
          builder: (context, data, reload) {
            final sessions = (data['sessions'] as List).cast<Map>(), closures = (data['closures'] as List).cast<Map>();
            if (sessions.isEmpty && closures.isEmpty) return const Center(child: Text('No bookings in this period.'));
            return Body(maxWidth: 960, children: [
              Text('Times in $zone', style: Theme.of(context).textTheme.bodySmall),
              for (final c in closures)
                Card(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  child: ListTile(
                    leading: const Icon(Icons.block),
                    title: Text('Closed: ${c['reason'] ?? ''}'),
                    subtitle: Text('${day(inZone(c['starts_at'], zone))} '
                        '${hm(inZone(c['starts_at'], zone))}–${hm(inZone(c['ends_at'], zone))}'),
                  ),
                ),
              for (final s in sessions) _session(context, s, owner, reload),
            ]);
          },
        ),
      ),
    ]);
  }

  Widget _session(BuildContext context, Map s, bool owner, VoidCallback reload) {
    final start = inZone(s['starts_at'], zone), end = inZone(s['ends_at'], zone);
    final ended = DateTime.parse(s['ends_at']).isBefore(DateTime.now());
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${days > 1 ? '${day(start)} ' : ''}${hm(start)}–${hm(end)} · ${s['court']['name']}',
                  style: Theme.of(context).textTheme.titleMedium),
            ),
            StatusChip(s['status']),
          ]),
          Text('${s['kind'] == 'training' ? 'Training' : 'Play'} · ${s['sport']['name']} · '
              '${s['accepted_count']} going'),
          Text('Booked by ${s['booker']['full_name']}'
              '${s['coach'] != null ? ' · coach ${s['coach']['full_name']}' : ''}'
              '${s['group'] != null ? ' · ${s['group']}' : ''}'),
          for (final r in s['rentals'])
            Row(children: [
              Expanded(child: Text('${r['equipment']['name']} × ${r['quantity']} · ${money(r['price'])}')),
              StatusChip(r['status']),
              if (r['status'] != 'approved' && s['status'] == 'confirmed')
                TextButton(onPressed: () => _decide(r, 'approved', reload), child: const Text('Approve')),
              if (r['status'] != 'declined' && s['status'] == 'confirmed')
                TextButton(onPressed: () => _decide(r, 'declined', reload), child: const Text('Decline')),
            ]),
          if (owner && s['status'] == 'confirmed' && !ended)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () async {
                  if (!await confirm(context, 'Cancel this session? Everyone on it is told.')) return;
                  if (context.mounted &&
                      await act(context, () => Api.instance.post('sessions/${s['id']}/cancel/'), done: 'Cancelled.')) {
                    reload();
                  }
                },
                child: const Text('Cancel session'),
              ),
            ),
        ]),
      ),
    );
  }

  Future<void> _decide(Map r, String status, VoidCallback reload) async {
    if (await act(context, () => Api.instance.patch('rentals/${r['id']}/', {'status': status}))) reload();
  }
}

/// Courts (CLUB-8 to CLUB-10); each opens its prices.
class _Courts extends StatelessWidget {
  const _Courts(this.club);
  final Map club;

  @override
  Widget build(BuildContext context) => Loaded(
        load: () async => [await Api.instance.rows('clubs/${club['id']}/courts/'), await sports()],
        builder: (context, data, reload) {
          final courts = data[0], sportList = data[1];
          return Body(children: [
            if (courts.isEmpty) const Text('No courts yet. Add one, then set its prices.'),
            for (final c in courts)
              Card(
                child: ListTile(
                  title: Text('${c['name']}${c['is_active'] ? '' : ' (inactive)'}'),
                  subtitle: Text('${(c['sports'] as List).map((id) => sportList.firstWhere((s) => s['id'] == id, orElse: () => {'name': '?'})['name']).join(', ')}'
                      ' · ${c['slot_minutes']}-minute slots'),
                  onTap: () => context.go('/clubs/${club['id']}/courts/${c['id']}/prices'),
                  trailing: IconButton(
                    icon: const Icon(Icons.edit),
                    tooltip: 'Edit court',
                    onPressed: () async {
                      if (await _courtDialog(context, club, c, sportList)) reload();
                    },
                  ),
                ),
              ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Add a court'),
              onPressed: () async {
                if (await _courtDialog(context, club, {'slot_minutes': 60, 'sports': [], 'is_active': true}, sportList)) {
                  reload();
                }
              },
            ),
          ]);
        },
      );
}

Future<bool> _courtDialog(BuildContext context, Map club, Map court, List<Map<String, dynamic>> sportList) async {
  final name = TextEditingController(text: court['name']),
      description = TextEditingController(text: court['description']),
      slot = TextEditingController(text: '${court['slot_minutes']}');
  final picked = {...(court['sports'] as List).cast<int>()};
  var active = court['is_active'] as bool;
  return await showDialog<bool>(
        context: context,
        builder: (c) => StatefulBuilder(
          builder: (c, setState) => AlertDialog(
            title: Text(court['id'] == null ? 'New court' : 'Edit court'),
            content: SizedBox(
              width: 420,
              child: SingleChildScrollView(
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  TextField(controller: name, decoration: const InputDecoration(labelText: 'Name')),
                  TextField(controller: description, decoration: const InputDecoration(labelText: 'Description')),
                  TextField(
                    controller: slot,
                    decoration: const InputDecoration(labelText: 'Slot length (minutes)', helperText: 'A multiple of 5, 15 to 480'),
                    keyboardType: TextInputType.number,
                  ),
                  const SizedBox(height: 12),
                  const Text('Sports'),
                  Wrap(spacing: 6, children: [
                    for (final s in sportList)
                      FilterChip(
                        label: Text(s['name']),
                        selected: picked.contains(s['id']),
                        onSelected: (on) => setState(() => on ? picked.add(s['id']) : picked.remove(s['id'])),
                      ),
                  ]),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Open for booking'),
                    value: active,
                    onChanged: (v) => setState(() => active = v),
                  ),
                ]),
              ),
            ),
            actions: [
              if (court['id'] != null)
                TextButton(
                  onPressed: () async {
                    if (await act(c, () => Api.instance.delete('courts/${court['id']}/')) && c.mounted) Navigator.pop(c, true);
                  },
                  child: const Text('Delete'),
                ),
              TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
              FilledButton(
                onPressed: () async {
                  final body = {
                    'name': name.text.trim(),
                    'description': description.text.trim(),
                    'slot_minutes': int.tryParse(slot.text.trim()),
                    'sports': picked.toList(),
                    'is_active': active,
                  };
                  final ok = await act(
                      c,
                      () => court['id'] == null
                          ? Api.instance.post('clubs/${club['id']}/courts/', body)
                          : Api.instance.patch('courts/${court['id']}/', body));
                  if (ok && c.mounted) Navigator.pop(c, true);
                },
                child: const Text('Save'),
              ),
            ],
          ),
        ),
      ) ??
      false;
}

/// A court's prices: weekday windows with a price per slot (CLUB-11 to CLUB-13).
class PricesScreen extends StatelessWidget {
  const PricesScreen({super.key, required this.court});
  final int court;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Opening hours and prices')),
        body: Loaded(
          load: () => Api.instance.rows('courts/$court/rates/'),
          builder: (context, rates, reload) => Body(children: [
            const Text('Each window is cut into slots of the court\'s length; the price is per slot, in USD. '
                'An end of 00:00 means midnight.'),
            for (var w = 0; w < 7; w++) ...[
              Heading(weekdays[w]),
              for (final r in rates.where((r) => r['weekday'] == w))
                ListTile(
                  dense: true,
                  title: Text('${clock(r['start_time'])}–${clock(r['end_time'], end: true)}   ${money(r['price'])}'),
                  onTap: () async {
                    if (await _rateDialog(context, court, r)) reload();
                  },
                  trailing: IconButton(
                    icon: const Icon(Icons.delete_outline),
                    tooltip: 'Delete',
                    onPressed: () async {
                      if (await act(context, () => Api.instance.delete('rates/${r['id']}/'))) reload();
                    },
                  ),
                ),
              if (!rates.any((r) => r['weekday'] == w)) const Text('Closed'),
            ],
            const SizedBox(height: 16),
            FilledButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Add hours'),
              onPressed: () async {
                if (await _rateDialog(context, court, {'start_time': '09:00', 'end_time': '17:00', 'price': ''})) reload();
              },
            ),
          ]),
        ),
      );
}

/// Add (to one or several weekdays at once) or edit a rate row.
Future<bool> _rateDialog(BuildContext context, int court, Map rate) async {
  final days = <int>{if (rate['weekday'] != null) rate['weekday']};
  var start = TimeOfDay(hour: int.parse(rate['start_time'].substring(0, 2)), minute: int.parse(rate['start_time'].substring(3, 5)));
  var end = TimeOfDay(hour: int.parse(rate['end_time'].substring(0, 2)), minute: int.parse(rate['end_time'].substring(3, 5)));
  final price = TextEditingController(text: '${rate['price']}');
  String t(TimeOfDay x) => '${x.hour.toString().padLeft(2, '0')}:${x.minute.toString().padLeft(2, '0')}';
  return await showDialog<bool>(
        context: context,
        builder: (c) => StatefulBuilder(
          builder: (c, setState) => AlertDialog(
            title: Text(rate['id'] == null ? 'Add hours' : 'Edit hours'),
            content: SizedBox(
              width: 420,
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                Wrap(spacing: 6, children: [
                  for (var w = 0; w < 7; w++)
                    FilterChip(
                      label: Text(weekdays[w].substring(0, 3)),
                      selected: days.contains(w),
                      onSelected: (on) => setState(() {
                        if (rate['id'] != null) days.clear(); // an existing row has one weekday
                        on ? days.add(w) : days.remove(w);
                      }),
                    ),
                ]),
                const SizedBox(height: 12),
                Row(children: [
                  OutlinedButton(
                    onPressed: () async {
                      final x = await showTimePicker(context: c, initialTime: start);
                      if (x != null) setState(() => start = x);
                    },
                    child: Text('From ${t(start)}'),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton(
                    onPressed: () async {
                      final x = await showTimePicker(context: c, initialTime: end);
                      if (x != null) setState(() => end = x);
                    },
                    child: Text('To ${t(end) == '00:00' ? '24:00' : t(end)}'),
                  ),
                ]),
                TextField(
                  controller: price,
                  decoration: const InputDecoration(labelText: 'Price per slot (USD)'),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                ),
              ]),
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
              FilledButton(
                onPressed: days.isEmpty
                    ? null
                    : () async {
                        Map body(int w) => {'weekday': w, 'start_time': t(start), 'end_time': t(end), 'price': price.text.trim()};
                        final ok = await act(c, () async {
                          if (rate['id'] != null) {
                            await Api.instance.patch('rates/${rate['id']}/', body(days.first));
                          } else {
                            for (final w in days.toList()..sort()) {
                              await Api.instance.post('courts/$court/rates/', body(w));
                            }
                          }
                        });
                        if (ok && c.mounted) Navigator.pop(c, true);
                      },
                child: const Text('Save'),
              ),
            ],
          ),
        ),
      ) ??
      false;
}

/// Amenities (no price) and rentables (with a price) (CLUB-18, CLUB-19, FE-7).
class _Equipment extends StatelessWidget {
  const _Equipment(this.club);
  final Map club;

  @override
  Widget build(BuildContext context) => Loaded(
        load: () async => [
          await Api.instance.rows('clubs/${club['id']}/equipment/'),
          await Api.instance.rows('clubs/${club['id']}/courts/'),
        ],
        builder: (context, data, reload) {
          final items = data[0], courts = data[1];
          String where(Map e) =>
              e['court'] == null ? 'All courts' : courts.firstWhere((c) => c['id'] == e['court'], orElse: () => {'name': '?'})['name'];
          Widget tile(Map e) => Card(
                child: ListTile(
                  title: Text('${e['name']} (${e['quantity']})'),
                  subtitle: Text('${where(e)}${e['rental_price'] == null ? '' : ' · ${money(e['rental_price'])} per booking'}'),
                  onTap: () async {
                    if (await _equipmentDialog(context, club, e, courts)) reload();
                  },
                ),
              );
          return Body(children: [
            const Heading('Amenities'),
            const Text('Free with every booking: balls, showers, parking.'),
            for (final e in items.where((e) => e['rental_price'] == null)) tile(e),
            const Heading('Rentables'),
            const Text('Players rent them with a booking; you approve each rental.'),
            for (final e in items.where((e) => e['rental_price'] != null)) tile(e),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Add an amenity or rentable'),
              onPressed: () async {
                if (await _equipmentDialog(context, club, {'quantity': 1}, courts)) reload();
              },
            ),
          ]);
        },
      );
}

Future<bool> _equipmentDialog(BuildContext context, Map club, Map item, List<Map<String, dynamic>> courts) async {
  final name = TextEditingController(text: item['name']), quantity = TextEditingController(text: '${item['quantity']}');
  final price = TextEditingController(text: item['rental_price'] ?? '');
  int? court = item['court'];
  var rentable = item['rental_price'] != null;
  return await showDialog<bool>(
        context: context,
        builder: (c) => StatefulBuilder(
          builder: (c, setState) => AlertDialog(
            title: Text(item['id'] == null ? 'New item' : 'Edit item'),
            content: SizedBox(
              width: 420,
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(controller: name, decoration: const InputDecoration(labelText: 'Name')),
                TextField(
                    controller: quantity,
                    decoration: const InputDecoration(labelText: 'How many the club has'),
                    keyboardType: TextInputType.number),
                DropdownButtonFormField<int?>(
                  initialValue: court,
                  decoration: const InputDecoration(labelText: 'Where'),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('All courts')),
                    for (final ct in courts) DropdownMenuItem(value: ct['id'] as int, child: Text(ct['name'])),
                  ],
                  onChanged: (v) => court = v,
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Rentable for a price'),
                  subtitle: const Text('Off: an amenity, free'),
                  value: rentable,
                  onChanged: (v) => setState(() => rentable = v),
                ),
                if (rentable)
                  TextField(
                    controller: price,
                    decoration: const InputDecoration(labelText: 'Price per booking (USD)'),
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  ),
              ]),
            ),
            actions: [
              if (item['id'] != null)
                TextButton(
                  onPressed: () async {
                    if (await act(c, () => Api.instance.delete('equipment/${item['id']}/')) && c.mounted) Navigator.pop(c, true);
                  },
                  child: const Text('Delete'),
                ),
              TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
              FilledButton(
                onPressed: () async {
                  final body = {
                    'name': name.text.trim(),
                    'quantity': int.tryParse(quantity.text.trim()),
                    'court': court,
                    'rental_price': rentable ? price.text.trim() : null,
                  };
                  final ok = await act(
                      c,
                      () => item['id'] == null
                          ? Api.instance.post('clubs/${club['id']}/equipment/', body)
                          : Api.instance.patch('equipment/${item['id']}/', body));
                  if (ok && c.mounted) Navigator.pop(c, true);
                },
                child: const Text('Save'),
              ),
            ],
          ),
        ),
      ) ??
      false;
}

/// Club staff (FE-12): added by email, removed by the owner (CLUB-25, CLUB-28).
class _Staff extends StatelessWidget {
  const _Staff(this.club);
  final Map club;

  @override
  Widget build(BuildContext context) => Loaded(
        load: () => Api.instance.rows('clubs/${club['id']}/members/'),
        builder: (context, members, reload) {
          final email = TextEditingController();
          final staff = members.where((m) => m['role'] == 'staff');
          return Body(children: [
            const Text('Staff see the schedule and approve rentals. They cannot change prices or courts.'),
            for (final m in staff)
              ListTile(
                title: Text(m['user']['full_name']),
                trailing: IconButton(
                  icon: const Icon(Icons.person_remove_outlined),
                  tooltip: 'Remove',
                  onPressed: () async {
                    if (await act(context, () => Api.instance.delete('members/${m['id']}/'))) reload();
                  },
                ),
              ),
            if (staff.isEmpty) const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: Text('No staff yet.')),
            Row(children: [
              Expanded(
                child: TextField(
                  controller: email,
                  decoration: const InputDecoration(labelText: 'Email of their PASS account'),
                  keyboardType: TextInputType.emailAddress,
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: () async {
                  final ok = await act(context,
                      () => Api.instance.post('clubs/${club['id']}/members/', {'email': email.text.trim(), 'role': 'staff'}),
                      done: 'Added.');
                  if (ok) reload();
                },
                child: const Text('Add'),
              ),
            ]),
          ]);
        },
      );
}
