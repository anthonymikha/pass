// Book tab (FE-10): find a court or a coach; a club's courts; a court's prices, amenities, rentables and free
// slots, with the quote before booking; a coach's profile and a training request (mvp.md, Player).
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
import '../shared.dart';

ApiClient get _api => ApiClient.instance;

/// GET /api/sports/ (CLUB-36).
Future<List<Map<String, dynamic>>> loadSports() async => asMaps(await _api.get('/api/sports/'));

class BookScreen extends StatefulWidget {
  const BookScreen({super.key});

  @override
  State<BookScreen> createState() => _BookScreenState();
}

class _BookScreenState extends State<BookScreen> {
  String _mode = 'courts';
  final _q = TextEditingController();
  String _query = '';
  int? _sport;

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PassScaffold(
        title: 'Book',
        children: [
          const LargeTitleHeader(title: 'Book'),
          PassSegmented<String>(
              values: const ['courts', 'coaches'],
              labelOf: (v) => v == 'courts' ? 'Courts' : 'Coaches',
              selected: _mode,
              onChanged: (v) => setState(() {
                    _mode = v;
                    _q.clear(); // a club name is no coach name
                    _query = '';
                  })),
          PassInput(
              controller: _q,
              placeholder: _mode == 'courts' ? 'Search clubs by name' : 'Search coaches by name',
              margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.l, PassSpace.gutter, 0),
              textInputAction: TextInputAction.search,
              onSubmitted: (v) => setState(() => _query = v.trim()),
              onChanged: (v) {
                if (v.isEmpty) setState(() => _query = '');
              }),
          if (_mode == 'courts') ...[
            ApiLoader<List<Map<String, dynamic>>>(
              load: loadSports,
              loading: const SizedBox(height: PassSpace.xxxl),
              builder: (context, sports, _) =>
                  SportChips(sports: sports, all: true, selected: _sport, onChanged: (v) => setState(() => _sport = v)),
            ),
            ApiLoader<List<dynamic>>(
              key: ValueKey('clubs-$_query-$_sport'),
              load: () => _api.getAll('/api/clubs/', query: {
                if (_query.isNotEmpty) 'q': _query,
                if (_sport != null) 'sport': '$_sport',
              }),
              builder: (context, data, _) {
                final clubs = asMaps(data);
                if (clubs.isEmpty) return const EmptyText('No clubs found.');
                return GroupedCard(inset: 0, children: [
                  for (final club in clubs)
                    ListRow(
                      label: '${club['name']}',
                      value: _courtCount(asMaps(club['courts']).length),
                      trailing: const Chevron(),
                      onTap: () => context.push('/book/clubs/${club['id']}'),
                    ),
                ]);
              },
            ),
          ] else
            ApiLoader<List<dynamic>>(
              key: ValueKey('coaches-$_query'),
              load: () => _api.getAll('/api/coaches/', query: {if (_query.isNotEmpty) 'q': _query}),
              builder: (context, data, _) {
                final coaches = asMaps(data);
                if (coaches.isEmpty) return const EmptyText('No coaches found.');
                return GroupedCard(inset: 0, children: [
                  for (final coach in coaches)
                    ListRow(
                      leading: Avatar(_initials('${coach['full_name']}'), size: 36, fontSize: 14),
                      label: '${coach['full_name']}',
                      value: coachRateLabel(coach),
                      trailing: const Chevron(),
                      onTap: () => context.push('/book/coaches/${coach['id']}'),
                    ),
                ]);
              },
            ),
        ],
      );
}

String _courtCount(int n) => n == 1 ? '1 court' : '$n courts';

String _initials(String name) {
  final p = name.trim().split(RegExp(r'\s+')).where((x) => x.isNotEmpty).toList();
  return p.isEmpty ? '?' : (p.first[0] + (p.length > 1 ? p.last[0] : '')).toUpperCase();
}

/// "25.00 USD / hour" (FE-4), or "" when the coach set no rate.
String coachRateLabel(Map<String, dynamic> coach) {
  final rate = coach['coach_rate'] as String?;
  return rate == null ? '' : '${money(rate, coach['coach_currency'] as String? ?? 'USD')} / hour';
}

class ClubScreen extends StatelessWidget {
  const ClubScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => ApiLoader<(Map<String, dynamic>, List<dynamic>)>(
        load: () async => (asMap(await _api.get('/api/clubs/$id/')), await _api.getAll('/api/clubs/$id/courts/')),
        builder: (context, data, _) {
          final (club, all) = data;
          final courts = asMaps(all).where((c) => c['is_active'] == true).toList();
          return PassScaffold(
            title: '${club['name']}',
            back: '/book',
            children: [
              LargeTitleHeader(title: '${club['name']}', subtitle: '${club['address']}'.isEmpty ? null : '${club['address']}'),
              const CapsHeader('Courts'),
              if (courts.isEmpty)
                const EmptyText('No courts to book yet.')
              else
                GroupedCard(inset: 0, children: [
                  for (final court in courts)
                    ListRow(
                        label: '${court['name']}',
                        trailing: const Chevron(),
                        onTap: () => context.push('/book/courts/${court['id']}')),
                ]),
            ],
          );
        },
      );
}

/// CLUB-31 court detail, then AVL-10 slots, BOOK-6 quote and BOOK-7 booking.
class CourtScreen extends StatefulWidget {
  const CourtScreen({super.key, required this.id});
  final int id;

  @override
  State<CourtScreen> createState() => _CourtScreenState();
}

class _CourtScreenState extends State<CourtScreen> {
  final _slots = GlobalKey<SlotRunPickerState>();
  SlotRun? _run;
  int? _sport;
  final Map<int, int> _rent = {}; // equipment id -> quantity
  Map<String, dynamic>? _quote;
  String? _quoteError;
  int _quoteSeq = 0;
  bool _busy = false;

  Map<String, Object?> _body(Map<String, dynamic> detail) => {
        'court': widget.id,
        'sport': _sport,
        'starts_at': _run!.startsAt,
        'ends_at': _run!.endsAt,
        'currency': asMap(detail['club'])['currency'],
        'rentals': [
          for (final e in _rent.entries)
            if (e.value > 0) {'equipment': e.key, 'quantity': e.value},
        ],
      };

  /// BOOK-6: the quote follows every change of run, sport or rentals.
  Future<void> _requote(Map<String, dynamic> detail) async {
    final seq = ++_quoteSeq;
    setState(() {
      _quote = null;
      _quoteError = null;
    });
    if (_run == null || _sport == null) return;
    try {
      final q = asMap(await _api.post('/api/sessions/quote/', body: _body(detail)));
      if (mounted && seq == _quoteSeq) setState(() => _quote = q);
    } on ApiException catch (e) {
      if (mounted && seq == _quoteSeq) setState(() => _quoteError = e.message);
    }
  }

  Future<void> _book(Map<String, dynamic> detail) async {
    setState(() => _busy = true);
    try {
      final s = asMap(await _api.post('/api/sessions/', body: _body(detail)));
      if (!mounted) return;
      final rented = _rent.values.any((q) => q > 0);
      await showPassAlert(context,
          title: 'Booked',
          message: rented
              ? 'The court is yours. Your rentables wait for the club’s approval.'
              : 'The court is yours.',
          actions: const [AlertAction('OK', kind: AlertKind.primary)]);
      if (mounted) context.go('/sessions/${s['id']}');
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.code == 'slot_taken') {
        await showPassAlert(context,
            title: 'Just taken',
            message: 'Someone booked this time a moment ago. Pick another time.',
            actions: const [AlertAction('OK', kind: AlertKind.primary)]);
        _slots.currentState?.reload();
      } else {
        await showErrorAlert(context, e, title: 'Not booked');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ApiLoader<Map<String, dynamic>>(
        load: () async => asMap(await _api.get('/api/courts/${widget.id}/')),
        builder: (context, detail, _) {
          final c = context.c;
          final club = asMap(detail['club']);
          final court = asMap(detail['court']);
          final zone = club['timezone'] as String;
          final currency = club['currency'] as String;
          final sports = asMaps(court['sports']);
          _sport ??= sports.isEmpty ? null : sports.first['id'] as int;
          final equipment = asMap(detail['equipment']);
          final included = asMaps(equipment['included']);
          final rentable = asMaps(equipment['rentable']);
          final rates = asMaps(detail['rates']);
          String scope(Map<String, dynamic> e) => e['court'] == null ? 'all courts' : 'this court';
          return PassScaffold(
            title: '${court['name']}',
            back: '/book/clubs/${club['id']}',
            children: [
              LargeTitleHeader(kicker: '${club['name']}', title: '${court['name']}',
                  subtitle: '${court['description']}'.isEmpty ? null : '${court['description']}'),
              Padding(
                padding: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.ml, PassSpace.gutter, 0),
                child: Wrap(spacing: PassSpace.xs, runSpacing: PassSpace.xs, children: [
                  for (final s in sports) SmallChip('${s['name']}'),
                  SmallChip('${court['slot_minutes']} min slots'),
                ]),
              ),
              CapsHeader('Prices · $zone time'),
              if (rates.isEmpty)
                const EmptyText('No prices set yet.')
              else
                GroupedCard(children: [
                  for (var d = 0; d < 7; d++)
                    if (rates.any((r) => r['weekday'] == d))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: PassSpace.m),
                        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          SizedBox(width: 100, child: Text(weekdays[d], style: PassText.body.copyWith(color: c.label))),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                              for (final r in rates.where((r) => r['weekday'] == d))
                                Text('${clock('${r['start_time']}')}–${clock('${r['end_time']}')} · ${money('${r['price']}', currency)}',
                                    style: PassText.subhead.copyWith(color: c.label2)),
                            ]),
                          ),
                        ]),
                      ),
                ]),
              FootnoteText('Price per ${court['slot_minutes']}-minute slot.'),
              const CapsHeader('Amenities · free with a booking'),
              if (included.isEmpty)
                const EmptyText('None listed.')
              else
                GroupedCard(inset: 0, children: [
                  for (final e in included) ListRow(label: '${e['name']}', value: scope(e)),
                ]),
              const CapsHeader('Book'),
              SlotRunPicker(
                  key: _slots,
                  courtId: widget.id,
                  clubZone: zone,
                  currency: currency,
                  onChanged: (run) {
                    _run = run;
                    _requote(detail);
                  }),
              if (sports.length > 1) ...[
                const CapsHeader('Sport'),
                PassSegmented<int>(
                    margin: kGutter,
                    values: [for (final s in sports) s['id'] as int],
                    labelOf: (id) => '${sports.firstWhere((s) => s['id'] == id)['name']}',
                    selected: _sport!,
                    onChanged: (v) {
                      _sport = v;
                      _requote(detail);
                    }),
              ],
              const CapsHeader('Rentables'),
              if (rentable.isEmpty)
                const EmptyText('Nothing to rent here.')
              else ...[
                GroupedCard(inset: 0, children: [
                  for (final e in rentable)
                    ListRow(
                      label: '${e['name']} · ${money('${e['rental_price']}', currency)}',
                      value: (_rent[e['id']] ?? 0) > 0 ? '×${_rent[e['id']]}' : null,
                      trailing: PassStepper(
                        onMinus: () {
                          final q = (_rent[e['id'] as int] ?? 0) - 1;
                          if (q < 0) return;
                          _rent[e['id'] as int] = q;
                          _requote(detail);
                        },
                        onPlus: () {
                          final q = (_rent[e['id'] as int] ?? 0) + 1;
                          if (q > (e['quantity'] as int)) return;
                          _rent[e['id'] as int] = q;
                          _requote(detail);
                        },
                      ),
                    ),
                ]),
                const FootnoteText('Rentables are subject to the club’s approval.'),
              ],
              if (_run != null) ...[
                CapsHeader('Quote · ${timeRange(at(_run!.startsAt, zone), at(_run!.endsAt, zone))}'),
                if (_quoteError != null)
                  NoticeBanner(text: _quoteError!, kind: NoticeKind.tint)
                else if (_quote == null)
                  const LoadingView()
                else
                  _quoteCard(context, _quote!),
              ],
              PassButton(
                _quote == null ? 'Pick a time' : 'Book · ${money('${_quote!['court_amount']}', '${_quote!['currency']}')}',
                margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.xxl, PassSpace.gutter, 0),
                enabled: _quote != null,
                busy: _busy,
                onPressed: () => _book(detail),
              ),
            ],
          );
        },
      );

  Widget _quoteCard(BuildContext context, Map<String, dynamic> q) {
    final cur = '${q['currency']}';
    final offer = q['offer'] as Map<String, dynamic>?;
    return GroupedCard(inset: 0, children: [
      ListRow(label: 'Court', value: money('${q['price']}', cur)),
      if (offer != null) ListRow(label: 'Offer: ${offer['message']}', value: '−${money('${q['discount_amount']}', cur)}'),
      for (final r in asMaps(q['rentals'])) ListRow(label: '${r['name']} ×${r['quantity']}', value: money('${r['price']}', cur)),
      ListRow(label: 'Total', value: money('${q['court_amount']}', cur)),
    ]);
  }
}

/// ACC-21 public profile, and BOOK-20 training request (FE-6: the player proposes, the coach confirms).
class CoachScreen extends StatefulWidget {
  const CoachScreen({super.key, required this.id});
  final int id;

  @override
  State<CoachScreen> createState() => _CoachScreenState();
}

class _CoachScreenState extends State<CoachScreen> {
  DateTime _start = nextHour(24);
  DateTime _end = nextHour(25);
  int? _sport;
  bool _busy = false;

  Future<void> _request() async {
    setState(() => _busy = true);
    try {
      final s = asMap(await _api.post('/api/training-requests/', body: {
        'coach': widget.id,
        'sport': _sport,
        'starts_at': iso(_start),
        'ends_at': iso(_end),
      }));
      if (!mounted) return;
      await showPassAlert(context,
          title: 'Request sent',
          message: 'The coach confirms the time, or proposes another one.',
          actions: const [AlertAction('OK', kind: AlertKind.primary)]);
      if (mounted) context.go('/sessions/${s['id']}');
    } on ApiException catch (e) {
      if (mounted) await showErrorAlert(context, e, title: 'Not sent');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ApiLoader<(Map<String, dynamic>, List<Map<String, dynamic>>)>(
        load: () async => (asMap(await _api.get('/api/users/${widget.id}/')), await loadSports()),
        builder: (context, data, _) {
          final (coach, sports) = data;
          _sport ??= sports.isEmpty ? null : sports.first['id'] as int;
          final clubs = asMaps(coach['clubs']);
          final self = AppState.instance.me?.id == widget.id;
          return PassScaffold(
            title: '${coach['full_name']}',
            back: '/book',
            children: [
              LargeTitleHeader(kicker: 'Coach', title: '${coach['full_name']}', subtitle: coachRateLabel(coach)),
              if ('${coach['coach_bio'] ?? ''}'.isNotEmpty) PassCard(child: Text('${coach['coach_bio']}')),
              if (clubs.isNotEmpty) ...[
                const CapsHeader('Clubs'),
                GroupedCard(inset: 0, children: [for (final cl in clubs) ListRow(label: '${cl['name']}')]),
              ],
              if (!self) ...[
                const CapsHeader('Request training'),
                SportChips(sports: sports, selected: _sport, onChanged: (v) => setState(() => _sport = v)),
                const SizedBox(height: PassSpace.ml),
                GroupedCard(inset: 0, children: [
                  DateTimeRow(
                      label: 'Starts',
                      value: _start,
                      onChanged: (v) => setState(() {
                            _end = v.add(_end.difference(_start));
                            _start = v;
                          })),
                  DateTimeRow(label: 'Ends', value: _end, onChanged: (v) => setState(() => _end = v)),
                ]),
                const FootnoteText('You propose a time. You can’t see the coach’s free times: the coach confirms '
                    'this time or another one, or declines.'),
                PassButton('Send request',
                    margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.xxl, PassSpace.gutter, 0),
                    enabled: _sport != null && _end.isAfter(_start),
                    busy: _busy,
                    onPressed: _request),
              ],
            ],
          );
        },
      );
}
