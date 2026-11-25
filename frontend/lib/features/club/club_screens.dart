// Club tab, for the club side only (FE-11): pick a club, its schedule with rentals to approve, and the owner's
// setup screens: details, courts, prices, amenities and rentables (FE-7), staff. Court times use the club's zone.
import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/format.dart';
import '../../theme/tokens.dart';
import '../../widgets/alerts.dart';
import '../../widgets/controls.dart';
import '../../widgets/layout.dart';
import '../../widgets/loader.dart';
import '../../widgets/scaffold.dart';
import '../book/book_screens.dart' show loadSports;
import '../sessions/sessions_screens.dart' show statusPill;
import '../shared.dart';

ApiClient get _api => ApiClient.instance;

Map<String, dynamic>? _clubOf(int id) => AppState.instance.clubSide.where((c) => c['id'] == id).firstOrNull;

/// Runs a write, shows its error, returns whether it worked.
Future<bool> _write(BuildContext context, Future<void> Function() call) async {
  try {
    await call();
    return true;
  } on ApiException catch (e) {
    if (context.mounted) await showErrorAlert(context, e);
    return false;
  }
}

EdgeInsets get _buttonMargin => const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.lg, PassSpace.gutter, 0);

class MyClubsScreen extends StatelessWidget {
  const MyClubsScreen({super.key});

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: AppState.instance,
        builder: (context, _) {
          final clubs = AppState.instance.clubSide;
          return PassScaffold(
            title: 'Club',
            onRefresh: AppState.instance.refresh,
            children: [
              const LargeTitleHeader(title: 'Club'),
              if (clubs.isEmpty)
                const EmptyText('You are not on the club side of any club.')
              else
                GroupedCard(inset: 0, children: [
                  for (final c in clubs)
                    ListRow(
                      label: '${c['name']}',
                      value: (c['roles'] as List).contains('owner') ? 'Owner' : 'Staff',
                      trailing: const Chevron(),
                      onTap: () => context.push('/club/${c['id']}'),
                    ),
                ]),
            ],
          );
        },
      );
}

/// RPT-1 schedule for one day, all courts or one; BOOK-40 rentals; BOOK-50 cancel (owner).
class ClubScheduleScreen extends StatefulWidget {
  const ClubScheduleScreen({super.key, required this.id});
  final int id;

  @override
  State<ClubScheduleScreen> createState() => _ClubScheduleScreenState();
}

class _ClubScheduleScreenState extends State<ClubScheduleScreen> {
  late final String _zone = '${_clubOf(widget.id)?['timezone'] ?? 'UTC'}';
  late final DateTime _today = clubToday(_zone);
  late DateTime _date = _today;
  int? _court;
  int _version = 0;

  Future<void> _rental(Map<String, dynamic> r, String status) async {
    if (await _write(context, () => _api.patch('/api/rentals/${r['id']}/', body: {'status': status}))) {
      setState(() => _version++);
    }
  }

  Future<void> _cancel(Map<String, dynamic> s) async {
    final ok = await showPassAlert(context,
        title: 'Cancel this session?',
        message: 'The court is freed and everyone in the session is told.',
        actions: const [AlertAction('Keep'), AlertAction('Cancel session', kind: AlertKind.destructive, value: 'go')]);
    if (ok == 'go' && mounted && await _write(context, () => _api.post('/api/sessions/${s['id']}/cancel/'))) {
      setState(() => _version++);
    }
  }

  @override
  Widget build(BuildContext context) {
    final club = _clubOf(widget.id);
    final owner = AppState.instance.isOwner(widget.id);
    return PassScaffold(
      title: '${club?['name'] ?? 'Club'}',
      back: '/club',
      maxWidth: PassSpace.contentMaxWidth,
      children: [
        LargeTitleHeader(
          kicker: 'Schedule · $_zone time',
          title: '${club?['name'] ?? ''}',
          trailing: owner ? PassLink('Setup', onTap: () => context.push('/club/${widget.id}/setup')) : null,
        ),
        const SizedBox(height: PassSpace.ml),
        DayChips(
            first: _today.subtract(const Duration(days: 7)),
            selected: _date,
            count: 68,
            onChanged: (d) => setState(() => _date = d)),
        ApiLoader<List<dynamic>>(
          load: () => _api.getAll('/api/clubs/${widget.id}/courts/'),
          loading: const SizedBox.shrink(),
          builder: (context, data, _) {
            final courts = asMaps(data);
            if (courts.length < 2) return const SizedBox.shrink();
            return PassSegmented<int>(
              values: [0, for (final c in courts) c['id'] as int],
              labelOf: (id) => id == 0 ? 'All courts' : '${courts.firstWhere((c) => c['id'] == id)['name']}',
              selected: _court ?? 0,
              onChanged: (v) => setState(() => _court = v == 0 ? null : v),
              fontSize: 13,
            );
          },
        ),
        const SizedBox(height: PassSpace.ml),
        ApiLoader<Map<String, dynamic>>(
          key: ValueKey('schedule-${ymd(_date)}-$_court-$_version'),
          load: () async => asMap(await _api.get('/api/clubs/${widget.id}/schedule/',
              query: {'from': ymd(_date), 'to': ymd(_date), if (_court != null) 'court': '$_court'})),
          builder: (context, data, _) {
            final sessions = asMaps(data['sessions']);
            final closures = asMaps(data['closures']);
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              for (final cl in closures)
                NoticeBanner(
                    bold: 'Closed ${hm(at('${cl['starts_at']}', _zone))}–${hm(at('${cl['ends_at']}', _zone))}',
                    text: '${cl['reason']}'),
              if (sessions.isEmpty) const EmptyText('No sessions on this day.'),
              for (final s in sessions) _session(context, s, owner),
            ]);
          },
        ),
      ],
    );
  }

  Widget _session(BuildContext context, Map<String, dynamic> s, bool owner) {
    final c = context.c;
    final coach = s['coach'] as Map<String, dynamic>?;
    final rentals = asMaps(s['rentals']);
    return PassCard(
      margin: const EdgeInsets.fromLTRB(PassSpace.gutter, 0, PassSpace.gutter, PassSpace.m),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(
            child: Text('${hm(at('${s['starts_at']}', _zone))}–${hm(at('${s['ends_at']}', _zone))} · ${asMap(s['court'])['name']}',
                style: PassText.headline.copyWith(color: c.label)),
          ),
          statusPill(context, '${s['status']}'),
        ]),
        const SizedBox(height: PassSpace.xs),
        Text(
            [
              '${asMap(s['sport'])['name']}${s['kind'] == 'training' ? ' training' : ''}',
              'Booked by ${asMap(s['booker'])['full_name']}',
              if (coach != null) 'Coach ${coach['full_name']}',
              if (s['group'] != null) '${s['group']}',
              '${s['accepted_count']} playing',
            ].join(' · '),
            style: PassText.subhead.copyWith(color: c.label2)),
        for (final r in rentals) ...[
          const SizedBox(height: PassSpace.sm),
          Row(children: [
            Expanded(
              child: Text('${asMap(r['equipment'])['name']} ×${r['quantity']} · ${r['status']}',
                  style: PassText.subhead.copyWith(color: c.label)),
            ),
            if (r['status'] != 'approved') PassLink('Approve', onTap: () => _rental(r, 'approved')),
            if (r['status'] != 'declined') ...[
              const SizedBox(width: PassSpace.l),
              PassLink('Decline', color: PassColors.destructive, onTap: () => _rental(r, 'declined')),
            ],
          ]),
        ],
        if (owner && s['status'] == 'confirmed') ...[
          const SizedBox(height: PassSpace.sm),
          Align(
              alignment: Alignment.centerRight,
              child: PassLink('Cancel session', color: PassColors.destructive, onTap: () => _cancel(s))),
        ],
      ]),
    );
  }
}

/// Owner: club details (CLUB-2), courts, and the ways to equipment and staff.
class ClubSetupScreen extends StatefulWidget {
  const ClubSetupScreen({super.key, required this.id});
  final int id;

  @override
  State<ClubSetupScreen> createState() => _ClubSetupScreenState();
}

class _ClubSetupScreenState extends State<ClubSetupScreen> {
  final _name = TextEditingController();
  final _address = TextEditingController();
  String? _zone;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _address.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    await _write(context, () async {
      await _api.patch('/api/clubs/${widget.id}/',
          body: {'name': _name.text.trim(), 'address': _address.text.trim(), 'timezone': _zone});
      await AppState.instance.refresh();
    });
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) => ApiLoader<(Map<String, dynamic>, List<dynamic>)>(
        load: () async =>
            (asMap(await _api.get('/api/clubs/${widget.id}/')), await _api.getAll('/api/clubs/${widget.id}/courts/')),
        builder: (context, data, _) {
          final (club, courts) = data;
          if (_zone == null) {
            _zone = '${club['timezone']}';
            _name.text = '${club['name']}';
            _address.text = '${club['address'] ?? ''}';
          }
          return PassScaffold(
            title: 'Setup',
            back: '/club/${widget.id}',
            children: [
              LargeTitleHeader(kicker: 'Setup', title: '${club['name']}'),
              const CapsHeader('Club'),
              GroupedCard(inset: 0, children: [
                FormFieldRow(label: 'Name', controller: _name),
                FormFieldRow(label: 'Address', controller: _address, placeholder: 'Optional'),
                PickerRow(label: 'Time zone', options: zoneNames(), value: _zone!, onChanged: (v) => setState(() => _zone = v)),
              ]),
              FootnoteText('Prices are in ${club['currency']}.'),
              PassButton('Save club', kind: PassButtonKind.secondary, margin: _buttonMargin, busy: _busy, onPressed: _save),
              const CapsHeader('Courts'),
              GroupedCard(inset: 0, children: [
                for (final c in asMaps(courts))
                  ListRow(
                    label: '${c['name']}',
                    value: c['is_active'] == true ? null : 'Inactive',
                    trailing: const Chevron(),
                    onTap: () => context.push('/club/${widget.id}/courts/${c['id']}'),
                  ),
                ListRow(
                    label: 'Add a court',
                    labelColor: context.c.tint,
                    onTap: () => context.push('/club/${widget.id}/courts/new')),
              ]),
              const CapsHeader('Equipment and people'),
              GroupedCard(inset: 0, children: [
                ListRow(
                    label: 'Amenities and rentables',
                    trailing: const Chevron(),
                    onTap: () => context.push('/club/${widget.id}/equipment')),
                ListRow(label: 'Staff', trailing: const Chevron(), onTap: () => context.push('/club/${widget.id}/staff')),
              ]),
            ],
          );
        },
      );
}

/// Owner: a court (CLUB-8, CLUB-9) and its prices (CLUB-11 to CLUB-13).
class CourtEditScreen extends StatefulWidget {
  const CourtEditScreen({super.key, required this.clubId, this.courtId});
  final int clubId;
  final int? courtId;

  @override
  State<CourtEditScreen> createState() => _CourtEditScreenState();
}

class _CourtEditScreenState extends State<CourtEditScreen> {
  final _name = TextEditingController();
  final _description = TextEditingController();
  int _slot = 60;
  Set<int> _sports = {};
  bool _active = true;
  bool _loaded = false;
  bool _busy = false;

  // Price window form (CLUB-11): one row per chosen weekday.
  Set<int> _days = {0, 1, 2, 3, 4};
  DateTime _from = DateTime(2000, 1, 1, 8);
  DateTime _to = DateTime(2000, 1, 1, 22);
  final _price = TextEditingController();
  int? _editingRate;
  int _ratesVersion = 0;

  static final _slotOptions = [for (var m = 15; m <= 480; m += 5) '$m min'];

  @override
  void dispose() {
    _name.dispose();
    _description.dispose();
    _price.dispose();
    super.dispose();
  }

  Future<void> _saveCourt() async {
    setState(() => _busy = true);
    final body = {
      'name': _name.text.trim(),
      'description': _description.text.trim(),
      'slot_minutes': _slot,
      'sports': _sports.toList(),
      'is_active': _active,
    };
    await _write(context, () async {
      if (widget.courtId == null) {
        final court = asMap(await _api.post('/api/clubs/${widget.clubId}/courts/', body: body));
        if (mounted) context.pushReplacement('/club/${widget.clubId}/courts/${court['id']}');
      } else {
        await _api.patch('/api/courts/${widget.courtId}/', body: body);
        if (mounted) {
          await showPassAlert(context, title: 'Saved', actions: const [AlertAction('OK', kind: AlertKind.primary)]);
        }
      }
    });
    if (mounted) setState(() => _busy = false);
  }

  String _clock(DateTime t) => hm(t);

  Future<void> _saveRate() async {
    final body = {'start_time': _clock(_from), 'end_time': _clock(_to), 'price': _price.text.trim()};
    final ok = await _write(context, () async {
      if (_editingRate != null) {
        await _api.patch('/api/rates/$_editingRate/', body: {...body, 'weekday': _days.first});
      } else {
        for (final d in _days.toList()..sort()) {
          await _api.post('/api/courts/${widget.courtId}/rates/', body: {...body, 'weekday': d});
        }
      }
    });
    if (!mounted) return;
    setState(() {
      _ratesVersion++;
      if (ok) {
        _editingRate = null;
        _price.clear();
      }
    });
  }

  Future<void> _deleteRate() async {
    if (await _write(context, () => _api.delete('/api/rates/$_editingRate/'))) {
      setState(() {
        _editingRate = null;
        _price.clear();
        _ratesVersion++;
      });
    }
  }

  DateTime _time(String api) {
    final p = api.split(':');
    return DateTime(2000, 1, 1, int.parse(p[0]), int.parse(p[1]));
  }

  @override
  Widget build(BuildContext context) => ApiLoader<(List<Map<String, dynamic>>, List<dynamic>)>(
        load: () async => (
          await loadSports(),
          widget.courtId == null ? <dynamic>[] : await _api.getAll('/api/clubs/${widget.clubId}/courts/'),
        ),
        builder: (context, data, _) {
          final c = context.c;
          final (sports, courts) = data;
          if (!_loaded && widget.courtId != null) {
            final court = asMaps(courts).firstWhere((x) => x['id'] == widget.courtId);
            _name.text = '${court['name']}';
            _description.text = '${court['description']}';
            _slot = court['slot_minutes'] as int;
            _sports = {...(court['sports'] as List).cast<int>()};
            _active = court['is_active'] == true;
          }
          _loaded = true;
          final isNew = widget.courtId == null;
          return PassScaffold(
            title: isNew ? 'New court' : _name.text,
            back: '/club/${widget.clubId}/setup',
            children: [
              LargeTitleHeader(kicker: 'Court', title: isNew ? 'New court' : _name.text),
              const CapsHeader('Court'),
              GroupedCard(inset: 0, children: [
                FormFieldRow(label: 'Name', controller: _name, placeholder: 'Court 1', onChanged: (_) => setState(() {})),
                FormFieldRow(label: 'About', controller: _description, placeholder: 'Optional'),
                PickerRow(
                    label: 'Slot length',
                    options: _slotOptions,
                    value: '$_slot min',
                    onChanged: (v) => setState(() => _slot = int.parse(v.split(' ').first))),
                ListRow(label: 'Bookable', trailing: PassSwitch(value: _active, onChanged: (v) => setState(() => _active = v))),
              ]),
              const FootnoteText('Turn Bookable off to take the court off PASS; its history stays.'),
              const CapsHeader('Sports'),
              GroupedCard(inset: 0, children: [
                for (final s in sports)
                  ListRow(
                    label: '${s['name']}',
                    trailing: CheckCircle(selected: _sports.contains(s['id'])),
                    onTap: () => setState(() =>
                        _sports.contains(s['id']) ? _sports.remove(s['id']) : _sports.add(s['id'] as int)),
                  ),
              ]),
              PassButton(isNew ? 'Add court' : 'Save court',
                  kind: isNew ? PassButtonKind.primary : PassButtonKind.secondary,
                  margin: _buttonMargin,
                  enabled: _name.text.trim().isNotEmpty && _sports.isNotEmpty,
                  busy: _busy,
                  onPressed: _saveCourt),
              if (!isNew) ...[
                const CapsHeader('Prices · club time'),
                ApiLoader<List<dynamic>>(
                  key: ValueKey('rates-$_ratesVersion'),
                  load: () => _api.getAll('/api/courts/${widget.courtId}/rates/'),
                  builder: (context, data, _) {
                    final rates = asMaps(data)
                      ..sort((a, b) => '${a['weekday']}${a['start_time']}'.compareTo('${b['weekday']}${b['start_time']}'));
                    if (rates.isEmpty) return const EmptyText('No prices yet: the court offers no slots.');
                    return GroupedCard(inset: 0, children: [
                      for (final r in rates)
                        ListRow(
                          label: weekdays[r['weekday'] as int],
                          value: '${clock('${r['start_time']}')}–${clock('${r['end_time']}')} · ${r['price']}',
                          trailing: CheckMark(visible: _editingRate == r['id']),
                          onTap: () => setState(() {
                            _editingRate = r['id'] as int;
                            _days = {r['weekday'] as int};
                            _from = _time('${r['start_time']}');
                            _to = _time('${r['end_time']}');
                            _price.text = '${r['price']}';
                          }),
                        ),
                    ]);
                  },
                ),
                CapsHeader(_editingRate == null ? 'Add a price window' : 'Change this window'),
                Padding(
                  padding: kGutter,
                  child: Wrap(spacing: PassSpace.s, runSpacing: PassSpace.s, children: [
                    for (var d = 0; d < 7; d++)
                      Pressable(
                        semanticLabel: weekdays[d],
                        onTap: () => setState(() => _editingRate != null
                            ? _days = {d}
                            : _days.contains(d)
                                ? _days.remove(d)
                                : _days.add(d)),
                        child: Container(
                          width: 44,
                          padding: const EdgeInsets.symmetric(vertical: PassSpace.sm),
                          decoration: BoxDecoration(
                              color: _days.contains(d) ? c.tint : c.bgCard,
                              borderRadius: BorderRadius.circular(PassRadii.slot)),
                          child: Text(weekdays[d].substring(0, 3),
                              textAlign: TextAlign.center,
                              style: PassText.subhead.copyWith(color: _days.contains(d) ? PassColors.white : c.label)),
                        ),
                      ),
                  ]),
                ),
                const SizedBox(height: PassSpace.m),
                GroupedCard(inset: 0, children: [
                  DateTimeRow(
                      label: 'From', value: _from, mode: CupertinoDatePickerMode.time, onChanged: (v) => setState(() => _from = v)),
                  DateTimeRow(
                      label: 'To', value: _to, mode: CupertinoDatePickerMode.time, onChanged: (v) => setState(() => _to = v)),
                  FormFieldRow(
                      label: 'Price per slot',
                      labelWidth: 120,
                      controller: _price,
                      placeholder: '0.00',
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      onChanged: (_) => setState(() {})),
                ]),
                const FootnoteText('To 00:00 means until midnight. Windows on one day may touch but not overlap.'),
                PassButton(_editingRate == null ? 'Add price window' : 'Save window',
                    margin: _buttonMargin,
                    enabled: _days.isNotEmpty && _price.text.trim().isNotEmpty,
                    onPressed: _saveRate),
                if (_editingRate != null) ...[
                  PassButton('Delete window', kind: PassButtonKind.fill, margin: _buttonMargin, onPressed: _deleteRate),
                  Center(
                    child: PassLink('Done',
                        padding: const EdgeInsets.all(PassSpace.ml),
                        onTap: () => setState(() {
                              _editingRate = null;
                              _price.clear();
                            })),
                  ),
                ],
              ],
            ],
          );
        },
      );
}

/// Owner: amenities (no price) and rentables (with a price), for one court or all (CLUB-18, CLUB-19, FE-7).
class EquipmentScreen extends StatefulWidget {
  const EquipmentScreen({super.key, required this.clubId});
  final int clubId;

  @override
  State<EquipmentScreen> createState() => _EquipmentScreenState();
}

class _EquipmentScreenState extends State<EquipmentScreen> {
  final _name = TextEditingController();
  final _quantity = TextEditingController(text: '1');
  final _price = TextEditingController();
  int? _court;
  int? _editing;
  int _version = 0;

  @override
  void dispose() {
    _name.dispose();
    _quantity.dispose();
    _price.dispose();
    super.dispose();
  }

  void _reset() {
    _editing = null;
    _court = null;
    _name.clear();
    _quantity.text = '1';
    _price.clear();
  }

  Future<void> _save() async {
    final body = {
      'name': _name.text.trim(),
      'quantity': int.tryParse(_quantity.text.trim()) ?? 0,
      'court': _court,
      'rental_price': _price.text.trim().isEmpty ? null : _price.text.trim(),
    };
    final ok = await _write(
        context,
        () => _editing == null
            ? _api.post('/api/clubs/${widget.clubId}/equipment/', body: body)
            : _api.patch('/api/equipment/$_editing/', body: body));
    if (ok && mounted) {
      setState(() {
        _reset();
        _version++;
      });
    }
  }

  Future<void> _delete() async {
    if (await _write(context, () => _api.delete('/api/equipment/$_editing/'))) {
      setState(() {
        _reset();
        _version++;
      });
    }
  }

  @override
  Widget build(BuildContext context) => ApiLoader<(List<dynamic>, List<dynamic>)>(
        key: ValueKey('equipment-$_version'),
        load: () async => (
          await _api.getAll('/api/clubs/${widget.clubId}/courts/'),
          await _api.getAll('/api/clubs/${widget.clubId}/equipment/'),
        ),
        builder: (context, data, _) {
          final courts = asMaps(data.$1);
          final items = asMaps(data.$2);
          String courtName(Object? id) =>
              id == null ? 'All courts' : '${courts.firstWhere((c) => c['id'] == id, orElse: () => {'name': '?'})['name']}';
          Widget list(String title, List<Map<String, dynamic>> rows, String empty) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  CapsHeader(title),
                  if (rows.isEmpty)
                    EmptyText(empty)
                  else
                    GroupedCard(inset: 0, children: [
                      for (final e in rows)
                        ListRow(
                          label: '${e['name']} ×${e['quantity']}',
                          value: [courtName(e['court']), if (e['rental_price'] != null) '${e['rental_price']}'].join(' · '),
                          trailing: CheckMark(visible: _editing == e['id']),
                          onTap: () => setState(() {
                            _editing = e['id'] as int;
                            _name.text = '${e['name']}';
                            _quantity.text = '${e['quantity']}';
                            _court = e['court'] as int?;
                            _price.text = '${e['rental_price'] ?? ''}';
                          }),
                        ),
                    ]),
                ],
              );
          return PassScaffold(
            title: 'Equipment',
            back: '/club/${widget.clubId}/setup',
            children: [
              const LargeTitleHeader(kicker: 'Setup', title: 'Amenities and rentables'),
              list('Amenities · free with a booking', items.where((e) => e['rental_price'] == null).toList(),
                  'No amenities yet.'),
              list('Rentables', items.where((e) => e['rental_price'] != null).toList(), 'No rentables yet.'),
              CapsHeader(_editing == null ? 'Add an item' : 'Change this item'),
              GroupedCard(inset: 0, children: [
                FormFieldRow(label: 'Name', controller: _name, placeholder: 'Balls', onChanged: (_) => setState(() {})),
                FormFieldRow(
                    label: 'Quantity',
                    controller: _quantity,
                    keyboardType: TextInputType.number,
                    onChanged: (_) => setState(() {})),
                PickerRow(
                    label: 'For',
                    options: ['All courts', for (final c in courts) '${c['name']}'],
                    value: courtName(_court),
                    onChanged: (v) => setState(
                        () => _court = v == 'All courts' ? null : courts.firstWhere((c) => c['name'] == v)['id'] as int)),
                FormFieldRow(
                    label: 'Rental price',
                    labelWidth: 120,
                    controller: _price,
                    placeholder: 'Empty = amenity',
                    keyboardType: const TextInputType.numberWithOptions(decimal: true)),
              ]),
              const FootnoteText('Leave the price empty for an amenity (free with a booking). Club-wide amenities '
                  'such as parking or showers have quantity 1.'),
              PassButton(_editing == null ? 'Add item' : 'Save item',
                  margin: _buttonMargin, enabled: _name.text.trim().isNotEmpty, onPressed: _save),
              if (_editing != null) ...[
                PassButton('Remove item', kind: PassButtonKind.fill, margin: _buttonMargin, onPressed: _delete),
                Center(
                    child: PassLink('Done',
                        padding: const EdgeInsets.all(PassSpace.ml), onTap: () => setState(_reset))),
              ],
            ],
          );
        },
      );
}

/// Owner: club staff by email (FE-11, CLUB-25, CLUB-28).
class StaffScreen extends StatefulWidget {
  const StaffScreen({super.key, required this.clubId});
  final int clubId;

  @override
  State<StaffScreen> createState() => _StaffScreenState();
}

class _StaffScreenState extends State<StaffScreen> {
  final _email = TextEditingController();
  int _version = 0;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    if (await _write(context,
        () => _api.post('/api/clubs/${widget.clubId}/members/', body: {'email': _email.text.trim(), 'role': 'staff'}))) {
      setState(() {
        _email.clear();
        _version++;
      });
    }
  }

  Future<void> _remove(Map<String, dynamic> m) async {
    final ok = await showPassAlert(context,
        title: 'Remove ${asMap(m['user'])['full_name']}?',
        message: 'They stop seeing the club’s schedule.',
        actions: const [AlertAction('Keep'), AlertAction('Remove', kind: AlertKind.destructive, value: 'go')]);
    if (ok == 'go' && mounted && await _write(context, () => _api.delete('/api/members/${m['id']}/'))) {
      setState(() => _version++);
    }
  }

  @override
  Widget build(BuildContext context) => PassScaffold(
        title: 'Staff',
        back: '/club/${widget.clubId}/setup',
        children: [
          const LargeTitleHeader(kicker: 'Setup', title: 'Staff'),
          ApiLoader<List<dynamic>>(
            key: ValueKey('staff-$_version'),
            load: () => _api.getAll('/api/clubs/${widget.clubId}/members/'),
            builder: (context, data, _) {
              final staff = asMaps(data).where((m) => m['role'] == 'staff').toList();
              if (staff.isEmpty) return const EmptyText('No staff yet.');
              return GroupedCard(inset: 0, children: [
                for (final m in staff)
                  ListRow(
                      label: '${asMap(m['user'])['full_name']}',
                      trailing: PassLink('Remove', color: PassColors.destructive, onTap: () => _remove(m))),
              ]);
            },
          ),
          const CapsHeader('Add staff'),
          GroupedCard(inset: 0, children: [
            FormFieldRow(
                controller: _email,
                placeholder: 'Their PASS email',
                keyboardType: TextInputType.emailAddress,
                onChanged: (_) => setState(() {}),
                onSubmitted: (_) => _add()),
          ]),
          const FootnoteText('Staff see the schedule and handle rentals. They cannot change the setup.'),
          PassButton('Add staff', margin: _buttonMargin, enabled: _email.text.trim().isNotEmpty, onPressed: _add),
        ],
      );
}
