// Book tab (FE-10), in pass_v1's layout with an Airbnb-style flow: find a club or a coach; a club (its courts and
// coaches); a court as a listing (amenities, rentables, prices) with a reserve bar; the calendar sheet with free
// slots; confirm (summary, rentables, quote) and the "Booked" hero. A coach's profile and a training request.
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

String _path(String path, Map<String, String> q) => Uri(path: path, queryParameters: q).toString();

/// pass_v1's caps column header over a list of cards ("CLUB ... COURTS").
Widget _columns(BuildContext context, String first, [String? second]) {
  final style = PassText.caption.copyWith(color: context.c.label2);
  return Padding(
    padding: const EdgeInsets.fromLTRB(34, PassSpace.l, 34, PassSpace.s),
    child: Row(children: [
      Expanded(child: Text(first.toUpperCase(), style: style)),
      if (second != null) Text(second.toUpperCase(), style: style),
    ]),
  );
}

/// pass_v1's court card: bold name with a value on the right, a line of text, chips.
Widget _card(BuildContext context,
    {required String title, String? value, String? text, List<String> chips = const [], required VoidCallback onTap}) {
  final c = context.c;
  return Padding(
    padding: const EdgeInsets.fromLTRB(PassSpace.gutter, 0, PassSpace.gutter, PassSpace.sm),
    child: Pressable(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: PassSpace.ml, horizontal: PassSpace.l),
        decoration: BoxDecoration(color: c.bgCard, borderRadius: BorderRadius.circular(PassRadii.notice)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: PassText.headline.copyWith(color: c.label), overflow: TextOverflow.ellipsis)),
            if (value != null) Text(value, style: PassText.callout.copyWith(color: c.tint, fontWeight: PassText.semibold)),
            const SizedBox(width: PassSpace.sm),
            const Chevron(),
          ]),
          if (text != null && text.isNotEmpty) ...[
            const SizedBox(height: PassSpace.xxs),
            Text(text, style: PassText.footnote.copyWith(color: c.label2)),
          ],
          if (chips.isNotEmpty) ...[
            const SizedBox(height: PassSpace.s),
            Wrap(spacing: PassSpace.xs, runSpacing: PassSpace.xs, children: [for (final t in chips) SmallChip(t)]),
          ],
        ]),
      ),
    ),
  );
}

/// A coach as a row (Airbnb's host line): avatar, name, rate.
Widget _coachRow(BuildContext context, Map<String, dynamic> coach) {
  final c = context.c;
  return Pressable(
    onTap: () => context.push('/book/coaches/${coach['id']}'),
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: PassSpace.m),
      child: Row(children: [
        Avatar(_initials('${coach['full_name']}'), size: 44, bg: c.tintBg, fg: c.tint),
        const SizedBox(width: PassSpace.ml),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${coach['full_name']}', style: PassText.callout.copyWith(fontWeight: PassText.semibold, color: c.label)),
            Text(coachRateLabel(coach).isEmpty ? 'Coach' : coachRateLabel(coach),
                style: PassText.footnote.copyWith(color: c.label2)),
          ]),
        ),
        const Chevron(),
      ]),
    ),
  );
}

class BookScreen extends StatefulWidget {
  const BookScreen({super.key});

  @override
  State<BookScreen> createState() => _BookScreenState();
}

class _BookScreenState extends State<BookScreen> {
  String _mode = 'courts';
  final _q = TextEditingController();
  String _query = '';
  Set<int> _sports = {};

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PassScaffold(
        title: 'Book',
        children: [
          const LargeTitleHeader(kicker: 'Book a session', title: 'What are we playing?'),
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
                  SportTags(sports: sports, all: true, selected: _sports, onChanged: (v) => setState(() => _sports = v)),
            ),
            ApiLoader<List<dynamic>>(
              key: ValueKey('clubs-$_query-${(_sports.toList()..sort()).join(',')}'),
              load: () => _api.getAll('/api/clubs/', query: {
                if (_query.isNotEmpty) 'q': _query,
                if (_sports.isNotEmpty) 'sport': [for (final s in _sports) '$s'],
              }),
              builder: (context, data, _) {
                final clubs = asMaps(data);
                if (clubs.isEmpty) return const EmptyText('No clubs found.');
                return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  _columns(context, 'Club', 'Courts'),
                  for (final club in clubs)
                    _card(context,
                        title: '${club['name']}',
                        value: '${asMaps(club['courts']).length}',
                        text: [
                          '${club['address'] ?? ''}',
                          if (club['distance_km'] != null) '${club['distance_km']} km',
                        ].where((t) => t.isNotEmpty).join(' · '),
                        chips: [for (final c in asMaps(club['courts'])) '${c['name']}'],
                        onTap: () => context.push('/book/clubs/${club['id']}')),
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
                return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  _columns(context, 'Coach'),
                  GroupedCard(children: [for (final coach in coaches) _coachRow(context, coach)]),
                ]);
              },
            ),
        ],
      );
}

String _initials(String name) {
  final p = name.trim().split(RegExp(r'\s+')).where((x) => x.isNotEmpty).toList();
  return p.isEmpty ? '?' : (p.first[0] + (p.length > 1 ? p.last[0] : '')).toUpperCase();
}

/// "25.00 USD / hour" (FE-4), or "" when the coach set no rate.
String coachRateLabel(Map<String, dynamic> coach) {
  final rate = coach['coach_rate'] as String?;
  return rate == null ? '' : '${money(rate, coach['coach_currency'] as String? ?? 'USD')} / hour';
}

/// A club as a listing: its courts, and the coaches who work there (Airbnb's hosts).
class ClubScreen extends StatelessWidget {
  const ClubScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => ApiLoader<(Map<String, dynamic>, List<dynamic>, List<Map<String, dynamic>>)>(
        load: () async => (
          asMap(await _api.get('/api/clubs/$id/')),
          await _api.getAll('/api/clubs/$id/courts/'),
          await loadSports(),
        ),
        builder: (context, data, _) {
          final (club, all, sports) = data;
          final courts = asMaps(all).where((c) => c['is_active'] == true).toList();
          return PassScaffold(
            title: '${club['name']}',
            back: '/book',
            children: [
              LargeTitleHeader(
                  kicker: 'Club',
                  title: '${club['name']}',
                  subtitle: '${club['address'] ?? ''}'.isEmpty ? null : '${club['address']}'),
              if (courts.isEmpty)
                const EmptyText('No courts to book yet.')
              else ...[
                _columns(context, 'Court', 'Slot'),
                for (final court in courts)
                  _card(context,
                      title: '${court['name']}',
                      value: '${court['slot_minutes']} min',
                      text: '${court['description'] ?? ''}',
                      chips: [
                        for (final s in sports)
                          if ((court['sports'] as List).contains(s['id'])) '${s['name']}'
                      ],
                      onTap: () => context.push('/book/courts/${court['id']}')),
              ],
              ApiLoader<List<dynamic>>(
                load: () => _api.getAll('/api/coaches/', query: {'club': '$id'}),
                loading: const SizedBox.shrink(),
                builder: (context, data, _) {
                  final coaches = asMaps(data);
                  if (coaches.isEmpty) return const SizedBox.shrink();
                  return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    const CapsHeader('Coaches here'),
                    GroupedCard(children: [for (final coach in coaches) _coachRow(context, coach)]),
                  ]);
                },
              ),
            ],
          );
        },
      );
}

/// The court's weekdays with a price window (0 = Monday): the only days it has slots.
Set<int> _openDays(Map<String, dynamic> detail) => {for (final r in asMaps(detail['rates'])) r['weekday'] as int};

/// The calendar and free slots in a sheet (Airbnb's dates sheet); the picked run, or null.
Future<SlotRun?> showAvailability(BuildContext context, Map<String, dynamic> detail) {
  final club = asMap(detail['club']);
  final court = asMap(detail['court']);
  final zone = '${club['timezone']}';
  SlotRun? run;
  return showCupertinoModalPopup<SlotRun>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setSheet) => Container(
        height: MediaQuery.sizeOf(ctx).height * .9,
        constraints: const BoxConstraints(maxWidth: PassSpace.formMaxWidth),
        decoration: BoxDecoration(
            color: ctx.c.bgGrouped,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(PassRadii.alert))),
        child: SafeArea(
          top: false,
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.gutter, PassSpace.ml, 0),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${court['name']} · $zone time', style: PassText.footnote.copyWith(color: ctx.c.label2)),
                    Text('When do you play?', style: PassText.title2.copyWith(color: ctx.c.label)),
                  ]),
                ),
                PassLink('Close',
                    padding: const EdgeInsets.all(PassSpace.sm), style: PassText.headline, onTap: () => Navigator.of(ctx).pop()),
              ]),
            ),
            Expanded(
              child: ListView(padding: const EdgeInsets.only(top: PassSpace.l), children: [
                SlotRunPicker(
                    courtId: court['id'] as int,
                    clubZone: zone,
                    currency: '${club['currency']}',
                    openWeekdays: _openDays(detail),
                    onChanged: (r) => setSheet(() => run = r)),
              ]),
            ),
            ActionBar(
              title: run == null ? 'Pick a time' : timeRange(at(run!.startsAt, zone), at(run!.endsAt, zone)),
              subtitle: run == null ? 'Free times show for the day you pick' : '${run!.minutes} min',
              action: 'Reserve',
              enabled: run != null,
              onPressed: () => Navigator.of(ctx).pop(run),
            ),
          ]),
        ),
      ),
    ),
  );
}

String _reservePath(int court, SlotRun run) =>
    _path('/book/courts/$court/reserve', {'from': run.startsAt, 'to': run.endsAt});

/// CLUB-31 court detail as a listing; the reserve bar opens the calendar sheet.
class CourtScreen extends StatelessWidget {
  const CourtScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => ApiLoader<Map<String, dynamic>>(
        load: () async => asMap(await _api.get('/api/courts/$id/')),
        builder: (context, detail, _) {
          final c = context.c;
          final club = asMap(detail['club']);
          final court = asMap(detail['court']);
          final zone = club['timezone'] as String;
          final currency = club['currency'] as String;
          final sports = asMaps(court['sports']);
          final equipment = asMap(detail['equipment']);
          final included = asMaps(equipment['included']);
          final rentable = asMaps(equipment['rentable']);
          final rates = asMaps(detail['rates']);
          // Display only: the cheapest window, compared as numbers (the app never adds money up).
          final from = rates.isEmpty
              ? null
              : rates.map((r) => '${r['price']}').reduce((a, b) => double.parse(a) <= double.parse(b) ? a : b);
          return PassScaffold(
            title: '${court['name']}',
            back: '/book/clubs/${club['id']}',
            bottom: ActionBar(
              title: from == null ? 'Not bookable yet' : 'From ${money(from, currency)}',
              subtitle: 'per ${court['slot_minutes']}-min slot',
              action: 'Pick a time',
              enabled: from != null,
              onPressed: () async {
                final run = await showAvailability(context, detail);
                if (run != null && context.mounted) context.push(_reservePath(id, run));
              },
            ),
            children: [
              LargeTitleHeader(
                  kicker: '${club['name']}',
                  title: '${court['name']}',
                  subtitle: '${court['description']}'.isEmpty ? null : '${court['description']}'),
              Padding(
                padding: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.ml, PassSpace.gutter, 0),
                child: Wrap(spacing: PassSpace.xs, runSpacing: PassSpace.xs, children: [
                  for (final s in sports) SmallChip('${s['name']}'),
                  SmallChip('${court['slot_minutes']} min slots'),
                ]),
              ),
              const CapsHeader('Amenities · free with a booking'),
              if (included.isEmpty)
                const EmptyText('None listed.')
              else
                Padding(
                  padding: kGutter,
                  child: Wrap(spacing: PassSpace.xs, runSpacing: PassSpace.xs, children: [
                    for (final e in included) SmallChip('${e['name']}', fg: c.label, bg: c.bgCard),
                  ]),
                ),
              const CapsHeader('Rentables'),
              if (rentable.isEmpty)
                const EmptyText('Nothing to rent here.')
              else ...[
                GroupedCard(inset: 0, children: [
                  for (final e in rentable)
                    ListRow(label: '${e['name']}', value: '${money('${e['rental_price']}', currency)} · ${e['quantity']} here'),
                ]),
                const FootnoteText('Add them when you book. The club approves them.'),
              ],
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
            ],
          );
        },
      );
}

/// Confirm (pass_v1's confirm step): the summary, sport, rentables and the quote (BOOK-6), then BOOK-7.
/// The time lives in the URL (`from`, `to`), so a refresh keeps it.
class ReserveScreen extends StatefulWidget {
  const ReserveScreen({super.key, required this.id, required this.from, required this.to});
  final int id;
  final String from, to;

  @override
  State<ReserveScreen> createState() => _ReserveScreenState();
}

class _ReserveScreenState extends State<ReserveScreen> {
  Map<String, dynamic>? _detail;
  int? _sport;
  final Map<int, int> _rent = {}; // equipment id -> quantity
  Map<String, dynamic>? _quote;
  String? _quoteError;
  int _quoteSeq = 0;
  bool _busy = false;

  Map<String, Object?> get _body => {
        'court': widget.id,
        'sport': _sport,
        'starts_at': widget.from,
        'ends_at': widget.to,
        'currency': asMap(_detail!['club'])['currency'],
        'rentals': [
          for (final e in _rent.entries)
            if (e.value > 0) {'equipment': e.key, 'quantity': e.value},
        ],
      };

  @override
  void didUpdateWidget(ReserveScreen old) {
    super.didUpdateWidget(old);
    if (old.from != widget.from || old.to != widget.to) _requote();
  }

  /// BOOK-6: the quote follows every change of time, sport or rentals.
  Future<void> _requote() async {
    final seq = ++_quoteSeq;
    setState(() {
      _quote = null;
      _quoteError = null;
    });
    if (_detail == null || _sport == null) return;
    try {
      final q = asMap(await _api.post('/api/sessions/quote/', body: _body));
      if (mounted && seq == _quoteSeq) setState(() => _quote = q);
    } on ApiException catch (e) {
      if (mounted && seq == _quoteSeq) setState(() => _quoteError = e.message);
    }
  }

  Future<void> _changeTime() async {
    final run = await showAvailability(context, _detail!);
    if (run != null && mounted) context.replace(_reservePath(widget.id, run));
  }

  Future<void> _book() async {
    setState(() => _busy = true);
    try {
      final s = asMap(await _api.post('/api/sessions/', body: _body));
      if (mounted) context.go('/book/booked/${s['id']}');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      if (e.code == 'slot_taken') {
        await showPassAlert(context,
            title: 'Just taken',
            message: 'Someone booked this time a moment ago. Pick another time.',
            actions: const [AlertAction('OK', kind: AlertKind.primary)]);
        if (mounted) await _changeTime();
      } else {
        await showErrorAlert(context, e, title: 'Not booked');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // The time comes from the URL: a hand-edited or cut link has none.
    if (DateTime.tryParse(widget.from) == null || DateTime.tryParse(widget.to) == null) {
      return PassScaffold(title: 'Confirm', back: '/book/courts/${widget.id}', children: [
        const LargeTitleHeader(kicker: 'Book a session', title: 'Confirm'),
        const EmptyText('This link has no time in it.'),
        PassButton('Pick a time', margin: flowButtonMargin, onPressed: () => context.go('/book/courts/${widget.id}')),
      ]);
    }
    return ApiLoader<Map<String, dynamic>>(
        load: () async => asMap(await _api.get('/api/courts/${widget.id}/')),
        builder: (context, detail, _) {
          final club = asMap(detail['club']);
          final court = asMap(detail['court']);
          final zone = '${club['timezone']}';
          final currency = '${club['currency']}';
          final sports = asMaps(court['sports']);
          final equipment = asMap(detail['equipment']);
          final included = asMaps(equipment['included']);
          final rentable = asMaps(equipment['rentable']);
          if (_detail == null) {
            _detail = detail;
            _sport = sports.isEmpty ? null : sports.first['id'] as int;
            WidgetsBinding.instance.addPostFrameCallback((_) => _requote());
          }
          final start = at(widget.from, zone), end = at(widget.to, zone);
          return PassScaffold(
            title: 'Confirm',
            back: '/book/courts/${widget.id}',
            bottom: ActionBar(
              title: _quote == null ? 'Getting the price…' : money('${_quote!['court_amount']}', '${_quote!['currency']}'),
              subtitle: 'Total',
              action: 'Book now',
              enabled: _quote != null,
              busy: _busy,
              onPressed: _book,
            ),
            children: [
              const LargeTitleHeader(kicker: 'Book a session', title: 'Confirm'),
              SummaryCard(rows: [
                ('Court', '${court['name']}, ${club['name']}'),
                ('When', '${timeRange(start, end)} ($zone)'),
                ('Length', '${end.difference(start).inMinutes} min'),
                if (sports.length == 1) ('Sport', '${sports.first['name']}'),
              ]),
              Padding(
                padding: kGutter,
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: PassLink('Change time', padding: const EdgeInsets.symmetric(vertical: PassSpace.ml), onTap: _changeTime),
                ),
              ),
              if (sports.length > 1) ...[
                const CapsHeader('Sport'),
                SportTags(
                    sports: sports,
                    single: true,
                    selected: {?_sport},
                    padding: kGutter,
                    onChanged: (v) {
                      _sport = v.first;
                      _requote();
                    }),
              ],
              if (included.isNotEmpty) ...[
                const CapsHeader('Included'),
                Padding(
                  padding: kGutter,
                  child: Wrap(spacing: PassSpace.xs, runSpacing: PassSpace.xs, children: [
                    for (final e in included) SmallChip('${e['name']}', fg: context.c.label, bg: context.c.bgCard),
                  ]),
                ),
              ],
              if (rentable.isNotEmpty) ...[
                const CapsHeader('Rentables'),
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
                          _requote();
                        },
                        onPlus: () {
                          final q = (_rent[e['id'] as int] ?? 0) + 1;
                          if (q > (e['quantity'] as int)) return;
                          _rent[e['id'] as int] = q;
                          _requote();
                        },
                      ),
                    ),
                ]),
                const FootnoteText('Rentables are subject to the club’s approval.'),
              ],
              const CapsHeader('Price'),
              if (_quoteError != null)
                NoticeBanner(text: _quoteError!, kind: NoticeKind.tint)
              else if (_quote == null)
                const LoadingView()
              else
                _quoteCard(context, _quote!),
            ],
          );
        },
      );
  }

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

/// pass_v1's "Booked" hero after BOOK-7.
class BookedScreen extends StatelessWidget {
  const BookedScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => PassScaffold(
        title: 'Booked',
        back: '/book',
        children: [
          ApiLoader<Map<String, dynamic>>(
            load: () async => asMap(await _api.get('/api/sessions/$id/')),
            builder: (context, s, _) {
              final court = asMap(s['court']);
              final start = at('${s['starts_at']}');
              return BookedBody(
                kicker: 'Booked',
                headline: '${asMap(s['sport'])['name']}, ${dayLabel(start)} ${hm(start)}.\n'
                    '${court['name']}, ${asMap(court['club'])['name']}.',
                body: asMaps(s['rentals']).isEmpty
                    ? 'The court is yours.'
                    : 'The court is yours. Your rentables wait for the club’s approval.',
                sessionId: id,
                againPath: '/book',
              );
            },
          ),
        ],
      );
}

/// ACC-21 public profile (Airbnb's host page), and BOOK-20 training request (FE-6: the player proposes, the coach
/// confirms).
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
          final c = context.c;
          final (coach, sports) = data;
          _sport ??= sports.isEmpty ? null : sports.first['id'] as int;
          final clubs = asMaps(coach['clubs']);
          final self = AppState.instance.me?.id == widget.id;
          final name = '${coach['full_name']}';
          final rate = coach['coach_rate'] as String?;
          final cur = '${coach['coach_currency'] ?? 'USD'}';
          return PassScaffold(
            title: name,
            back: '/book',
            children: [
              Padding(
                padding: const EdgeInsets.only(top: PassSpace.l),
                child: Column(children: [
                  Avatar(_initials(name), size: 96, bg: c.tint, fg: PassColors.white),
                  const SizedBox(height: PassSpace.ml),
                  Text(name, style: PassText.title1.copyWith(color: c.label)),
                  const SizedBox(height: PassSpace.xxs),
                  Text('Coach', style: PassText.subhead.copyWith(color: c.label2)),
                ]),
              ),
              const SizedBox(height: PassSpace.lg),
              Padding(
                padding: kGutter,
                child: Row(children: [
                  Expanded(
                    child: StatTile(
                        kicker: 'Rate',
                        note: rate == null ? 'Agreed per session' : '$cur per hour',
                        child: StatValue(rate == null ? '—' : money(rate, cur).split(' ').first)),
                  ),
                  const SizedBox(width: PassSpace.ml),
                  Expanded(
                    child: StatTile(
                        kicker: 'Clubs', note: clubs.length == 1 ? 'club' : 'clubs', child: StatValue('${clubs.length}')),
                  ),
                ]),
              ),
              if ('${coach['coach_bio'] ?? ''}'.isNotEmpty) ...[
                CapsHeader('About ${name.split(' ').first}'),
                PassCard(child: Text('${coach['coach_bio']}', style: PassText.body.copyWith(color: c.label))),
              ],
              if (clubs.isNotEmpty) ...[
                const CapsHeader('Coaches at'),
                GroupedCard(inset: 0, children: [
                  for (final cl in clubs)
                    ListRow(label: '${cl['name']}', trailing: const Chevron(), onTap: () => context.push('/book/clubs/${cl['id']}')),
                ]),
              ],
              if (!self) ...[
                const CapsHeader('Request training'),
                SportTags(
                    sports: sports,
                    single: true,
                    selected: {?_sport},
                    padding: kGutter,
                    onChanged: (v) => setState(() => _sport = v.first)),
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
                    margin: flowButtonMargin,
                    enabled: _sport != null && _end.isAfter(_start),
                    busy: _busy,
                    onPressed: _request),
              ],
            ],
          );
        },
      );
}
