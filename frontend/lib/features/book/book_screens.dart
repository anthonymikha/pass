// Book tab (FE-10), in pass_v1's layout with an Airbnb-style flow: find a club or a coach; a club (its courts and
// coaches); a court as a listing (what it offers, rentables, prices) with a reserve bar; then the steps: days (the
// iOS calendar, several at once), times and prices per day, extras (sport, rentables), confirm and book, "Booked".
// A coach's profile and a training request.
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
import '../../widgets/svg_icon.dart';
import '../shared.dart';

ApiClient get _api => ApiClient.instance;

/// GET /api/sports/ (CLUB-36).
Future<List<Map<String, dynamic>>> loadSports() async => asMaps(await _api.get('/api/sports/'));

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

Future<Map<String, dynamic>> _loadCourt(int id) async => asMap(await _api.get('/api/courts/$id/'));

/// A court booking on its way through the steps (days, times, extras, confirm), carried in the URL so a refresh
/// keeps it: `day` per picked day, `from`/`to` per booking, `sport`, `rent` as `equipment:quantity`.
class Trip {
  const Trip(this.court, {this.days = const [], this.runs = const [], this.sport, this.rent = const {}});
  final int court;
  final List<String> days; // YYYY-MM-DD, club time
  final List<(String, String)> runs; // (starts_at, ends_at)
  final int? sport;
  final Map<int, int> rent;

  factory Trip.of(int court, Uri uri) {
    final q = uri.queryParametersAll;
    final from = q['from'] ?? const [], to = q['to'] ?? const [];
    return Trip(court,
        days: q['day'] ?? const [],
        runs: [for (var i = 0; i < from.length && i < to.length; i++) (from[i], to[i])],
        sport: int.tryParse(uri.queryParameters['sport'] ?? ''),
        rent: {
          for (final r in q['rent'] ?? const <String>[])
            if (r.split(':') case [final e, final n] when int.tryParse(e) != null && (int.tryParse(n) ?? 0) > 0)
              int.parse(e): int.parse(n),
        });
  }

  Trip copy({List<String>? days, List<(String, String)>? runs, int? sport, Map<int, int>? rent}) =>
      Trip(court, days: days ?? this.days, runs: runs ?? this.runs, sport: sport ?? this.sport, rent: rent ?? this.rent);

  String path(String step) => Uri(path: '/book/courts/$court/$step', queryParameters: {
        if (days.isNotEmpty) 'day': days,
        if (runs.isNotEmpty) 'from': [for (final r in runs) r.$1],
        if (runs.isNotEmpty) 'to': [for (final r in runs) r.$2],
        if (sport != null) 'sport': '$sport',
        if (rent.isNotEmpty) 'rent': [for (final e in rent.entries) '${e.key}:${e.value}'],
      }).toString();

  /// The booking body of one run (BOOK-6, BOOK-7).
  Map<String, Object?> body((String, String) run, String currency) => {
        'court': court,
        'sport': sport,
        'starts_at': run.$1,
        'ends_at': run.$2,
        'currency': currency,
        'rentals': [for (final e in rent.entries) {'equipment': e.key, 'quantity': e.value}],
      };
}

String _plural(int n, String one) => '$n $one${n == 1 ? '' : 's'}';

/// Airbnb's dates sheet: the iOS calendar, several days at once (only days the court has prices); null if closed.
Future<List<String>?> showDays(BuildContext context, Map<String, dynamic> detail, [List<String> initial = const []]) {
  final club = asMap(detail['club']);
  final court = asMap(detail['court']);
  final zone = '${club['timezone']}';
  final today = clubToday(zone);
  final open = _openDays(detail);
  final days = {for (final d in initial) DateTime.parse(d)};
  return showCupertinoModalPopup<List<String>>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setSheet) {
        final sorted = days.toList()..sort();
        return Container(
          constraints: const BoxConstraints(maxWidth: PassSpace.formMaxWidth),
          decoration: BoxDecoration(
              color: ctx.c.bgGrouped, borderRadius: const BorderRadius.vertical(top: Radius.circular(PassRadii.alert))),
          child: SafeArea(
            top: false,
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.gutter, PassSpace.ml, PassSpace.l),
                child: Row(children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${court['name']} · pick one or more days', style: PassText.footnote.copyWith(color: ctx.c.label2)),
                      Text('When do you play?', style: PassText.title2.copyWith(color: ctx.c.label)),
                    ]),
                  ),
                  PassLink('Close',
                      padding: const EdgeInsets.all(PassSpace.sm),
                      style: PassText.headline,
                      onTap: () => Navigator.of(ctx).pop()),
                ]),
              ),
              PassCard(
                padding: const EdgeInsets.all(PassSpace.ml),
                child: PassCalendar(
                  selected: days,
                  first: today,
                  last: today.add(const Duration(days: bookingHorizonDays)),
                  isOpen: (d) => open.contains(d.weekday - 1),
                  onChanged: (d) => setSheet(() => days.contains(d) ? days.remove(d) : days.add(d)),
                ),
              ),
              if (days.isNotEmpty)
                Padding(
                  padding: kGutter,
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: PassLink('Clear dates',
                        padding: const EdgeInsets.only(top: PassSpace.ml), onTap: () => setSheet(days.clear)),
                  ),
                ),
              ActionBar(
                title: days.isEmpty ? 'Add your days' : _plural(days.length, 'day'),
                subtitle: days.isEmpty ? 'Free times and prices come next' : sorted.map(dayLabel).join(', '),
                action: 'Next',
                enabled: days.isNotEmpty,
                onPressed: () => Navigator.of(ctx).pop([for (final d in sorted) ymd(d)]),
              ),
            ]),
          ),
        );
      },
    ),
  );
}

/// CLUB-31 court detail as a listing; the reserve bar opens the days sheet.
class CourtScreen extends StatelessWidget {
  const CourtScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => ApiLoader<Map<String, dynamic>>(
        load: () => _loadCourt(id),
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
          // Display only: the cheapest window, compared as numbers.
          final from = rates.isEmpty
              ? null
              : rates.map((r) => '${r['price']}').reduce((a, b) => double.parse(a) <= double.parse(b) ? a : b);
          return PassScaffold(
            title: '${court['name']}',
            back: '/book/clubs/${club['id']}',
            bottom: ActionBar(
              title: from == null ? 'Not bookable yet' : 'From ${money(from, currency)}',
              subtitle: 'per ${court['slot_minutes']}-min slot',
              action: 'Add dates',
              enabled: from != null,
              onPressed: () async {
                final days = await showDays(context, detail);
                if (days != null && context.mounted) context.push(Trip(id, days: days).path('times'));
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
              const CapsHeader('What this court offers'),
              _offers(context, included),
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

/// Airbnb's "What this place offers": what comes free with a booking, a check on each line.
Widget _offers(BuildContext context, List<Map<String, dynamic>> included) => included.isEmpty
    ? const EmptyText('Nothing included.')
    : GroupedCard(inset: 0, children: [
        for (final e in included)
          ListRow(
              leading: SvgIcon(PassIcons.check,
                  color: context.c.tint, viewBox: const Size(18, 14), width: 16, height: 13, stroke: 2.2),
              label: '${e['name']}'),
      ]);

/// Step 2: each picked day's free times with their prices; one run per day.
class TimesScreen extends StatefulWidget {
  const TimesScreen({super.key, required this.trip});
  final Trip trip;

  @override
  State<TimesScreen> createState() => _TimesScreenState();
}

class _TimesScreenState extends State<TimesScreen> {
  late List<String> _days = widget.trip.days;
  Map<String, (String, String)>? _runs; // day -> run

  Future<void> _changeDays(Map<String, dynamic> detail) async {
    final days = await showDays(context, detail, _days);
    if (days == null || !mounted) return;
    setState(() {
      _days = days;
      _runs!.removeWhere((d, _) => !days.contains(d));
    });
  }

  @override
  Widget build(BuildContext context) => ApiLoader<Map<String, dynamic>>(
        load: () => _loadCourt(widget.trip.court),
        builder: (context, detail, _) {
          final club = asMap(detail['club']);
          final court = asMap(detail['court']);
          final zone = '${club['timezone']}';
          final runs = _runs ??= {for (final r in widget.trip.runs) ymd(at(r.$1, zone)): r};
          final picked = [for (final d in _days) ?runs[d]];
          return PassScaffold(
            title: 'Times',
            back: '/book/courts/${widget.trip.court}',
            bottom: ActionBar(
              title: picked.isEmpty
                  ? 'Pick your times'
                  : picked.length == 1
                      ? timeRange(at(picked.first.$1, zone), at(picked.first.$2, zone))
                      : '${picked.length} of ${_plural(_days.length, 'day')}',
              subtitle: picked.isEmpty ? 'Tap a start, then a later slot for longer' : 'Extras come next',
              action: 'Next',
              enabled: picked.isNotEmpty,
              onPressed: () => context.push(
                  widget.trip.copy(days: _days, runs: picked).path('extras')),
            ),
            children: [
              LargeTitleHeader(
                  kicker: '${court['name']}, ${club['name']}',
                  title: 'Pick your times',
                  subtitle: '$zone time · price per slot'),
              Padding(
                padding: kGutter,
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: PassLink('Change days',
                      padding: const EdgeInsets.only(top: PassSpace.sm), onTap: () => _changeDays(detail)),
                ),
              ),
              if (_days.isEmpty) const EmptyText('No days picked.'),
              for (final d in _days) ...[
                CapsHeader(dayLabel(DateTime.parse(d))),
                SlotGrid(
                    key: ValueKey(d),
                    courtId: widget.trip.court,
                    date: DateTime.parse(d),
                    clubZone: zone,
                    currency: '${club['currency']}',
                    initial: runs[d],
                    onChanged: (r) => setState(() => r == null ? runs.remove(d) : runs[d] = (r.startsAt, r.endsAt))),
              ],
            ],
          );
        },
      );
}

/// Step 3: what comes with the court, the sport, and rentables (the club approves them).
class ExtrasScreen extends StatefulWidget {
  const ExtrasScreen({super.key, required this.trip});
  final Trip trip;

  @override
  State<ExtrasScreen> createState() => _ExtrasScreenState();
}

class _ExtrasScreenState extends State<ExtrasScreen> {
  late final Map<int, int> _rent = {...widget.trip.rent};
  late int? _sport = widget.trip.sport;

  @override
  Widget build(BuildContext context) => ApiLoader<Map<String, dynamic>>(
        load: () => _loadCourt(widget.trip.court),
        builder: (context, detail, _) {
          final club = asMap(detail['club']);
          final court = asMap(detail['court']);
          final currency = '${club['currency']}';
          final sports = asMaps(court['sports']);
          final equipment = asMap(detail['equipment']);
          final rentable = asMaps(equipment['rentable']);
          if (sports.isNotEmpty && !sports.any((s) => s['id'] == _sport)) _sport = sports.first['id'] as int;
          final items = _rent.values.fold(0, (a, b) => a + b);
          return PassScaffold(
            title: 'Extras',
            back: widget.trip.path('times'),
            bottom: ActionBar(
              title: items == 0 ? 'No rentables' : _plural(items, 'rentable'),
              subtitle: _plural(widget.trip.runs.length, 'booking'),
              action: 'Review',
              enabled: _sport != null && widget.trip.runs.isNotEmpty,
              onPressed: () => context.push(widget.trip
                  .copy(sport: _sport, rent: {for (final e in _rent.entries) if (e.value > 0) e.key: e.value})
                  .path('reserve')),
            ),
            children: [
              LargeTitleHeader(kicker: '${court['name']}, ${club['name']}', title: 'Add extras'),
              const CapsHeader('Included with the court'),
              _offers(context, asMaps(equipment['included'])),
              if (sports.length > 1) ...[
                const CapsHeader('Sport'),
                SportTags(
                    sports: sports,
                    single: true,
                    selected: {?_sport},
                    padding: kGutter,
                    onChanged: (v) => setState(() => _sport = v.first)),
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
                        onMinus: () => setState(() {
                          final q = (_rent[e['id'] as int] ?? 0) - 1;
                          if (q >= 0) _rent[e['id'] as int] = q;
                        }),
                        onPlus: () => setState(() {
                          final q = (_rent[e['id'] as int] ?? 0) + 1;
                          if (q <= (e['quantity'] as int)) _rent[e['id'] as int] = q;
                        }),
                      ),
                    ),
                ]),
                FootnoteText(widget.trip.runs.length > 1
                    ? 'For each booking. Rentables are subject to the club’s approval.'
                    : 'Rentables are subject to the club’s approval.'),
              ],
            ],
          );
        },
      );
}

/// Step 4 (Airbnb's "Confirm and pay"): the summary and the quote of each booking (BOOK-6), then BOOK-7 for each.
class ReserveScreen extends StatefulWidget {
  const ReserveScreen({super.key, required this.trip});
  final Trip trip;

  @override
  State<ReserveScreen> createState() => _ReserveScreenState();
}

class _ReserveScreenState extends State<ReserveScreen> {
  bool _busy = false;

  /// The court detail and one quote per booking; a refused quote is its ApiException.
  Future<(Map<String, dynamic>, List<Object>)> _load() async {
    final detail = await _loadCourt(widget.trip.court);
    final currency = '${asMap(detail['club'])['currency']}';
    final quotes = await Future.wait([
      for (final r in widget.trip.runs)
        _api
            .post('/api/sessions/quote/', body: widget.trip.body(r, currency))
            .then<Object>((q) => q as Object)
            .catchError((Object e) => e, test: (e) => e is ApiException),
    ]);
    return (detail, quotes);
  }

  Future<void> _book(String currency) async {
    setState(() => _busy = true);
    final ids = <int>[];
    try {
      for (final r in widget.trip.runs) {
        ids.add(asMap(await _api.post('/api/sessions/', body: widget.trip.body(r, currency)))['id'] as int);
      }
      if (mounted) context.go('/book/booked/${ids.join(',')}');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      if (ids.isNotEmpty) {
        await showPassAlert(context,
            title: 'Booked ${ids.length} of ${widget.trip.runs.length}',
            message: e.message,
            actions: const [AlertAction('OK', kind: AlertKind.primary)]);
        if (mounted) context.go('/book/booked/${ids.join(',')}');
      } else if (e.code == 'slot_taken') {
        await showPassAlert(context,
            title: 'Just taken',
            message: 'Someone booked this time a moment ago. Pick another time.',
            actions: const [AlertAction('OK', kind: AlertKind.primary)]);
        if (mounted) context.go(widget.trip.path('times'));
      } else {
        await showErrorAlert(context, e, title: 'Not booked');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final trip = widget.trip;
    // The times come from the URL: a hand-edited or cut link has none.
    if (trip.runs.isEmpty || trip.runs.any((r) => DateTime.tryParse(r.$1) == null || DateTime.tryParse(r.$2) == null)) {
      return PassScaffold(title: 'Confirm', back: '/book/courts/${trip.court}', children: [
        const LargeTitleHeader(kicker: 'Book a session', title: 'Confirm'),
        const EmptyText('This link has no time in it.'),
        PassButton('Pick a time', margin: flowButtonMargin, onPressed: () => context.go('/book/courts/${trip.court}')),
      ]);
    }
    return ApiLoader<(Map<String, dynamic>, List<Object>)>(
      key: ValueKey(trip.path('reserve')),
      load: _load,
      builder: (context, data, _) {
        final (detail, quotes) = data;
        final club = asMap(detail['club']);
        final court = asMap(detail['court']);
        final zone = '${club['timezone']}';
        final currency = '${club['currency']}';
        final sports = asMaps(court['sports']);
        final sport = sports.where((s) => s['id'] == trip.sport).firstOrNull;
        final rentable = {for (final e in asMaps(asMap(detail['equipment'])['rentable'])) e['id']: '${e['name']}'};
        final refused = quotes.whereType<ApiException>().firstOrNull;
        final ok = quotes.whereType<Map<String, dynamic>>().toList();
        final total = refused == null ? sumMoney([for (final q in ok) '${q['court_amount']}']) : null;
        final n = trip.runs.length;
        return PassScaffold(
          title: 'Confirm',
          back: trip.path('extras'),
          bottom: ActionBar(
            title: total == null ? 'Pick other times' : money(total, currency),
            subtitle: n == 1 ? 'Total' : 'Total · ${_plural(n, 'booking')}',
            action: n == 1 ? 'Book now' : 'Book $n',
            enabled: total != null && sport != null,
            busy: _busy,
            onPressed: () => _book(currency),
          ),
          children: [
            const LargeTitleHeader(kicker: 'Book a session', title: 'Confirm and book'),
            SummaryCard(rows: [
              ('Court', '${court['name']}, ${club['name']}'),
              ('Sport', '${sport?['name'] ?? '—'}'),
              ('Rentables',
                  trip.rent.isEmpty ? 'None' : [for (final e in trip.rent.entries) '${rentable[e.key]} ×${e.value}'].join(', ')),
            ]),
            Padding(
              padding: kGutter,
              child: Wrap(spacing: PassSpace.xl, children: [
                PassLink('Change times',
                    padding: const EdgeInsets.symmetric(vertical: PassSpace.ml), onTap: () => context.go(trip.path('times'))),
                PassLink('Change extras',
                    padding: const EdgeInsets.symmetric(vertical: PassSpace.ml), onTap: () => context.go(trip.path('extras'))),
              ]),
            ),
            CapsHeader('Price details · $zone time'),
            if (refused != null) NoticeBanner(text: refused.message, kind: NoticeKind.tint),
            GroupedCard(inset: 0, children: [
              for (var i = 0; i < n; i++) ...[
                ListRow(
                    label: timeRange(at(trip.runs[i].$1, zone), at(trip.runs[i].$2, zone)),
                    value: quotes[i] is Map ? money('${asMap(quotes[i])['price']}', currency) : 'Taken'),
                if (quotes[i] is Map) ...[
                  if (asMap(quotes[i])['offer'] case final Map offer)
                    ListRow(
                        label: 'Offer: ${offer['message']}',
                        value: '−${money('${asMap(quotes[i])['discount_amount']}', currency)}'),
                  for (final r in asMaps(asMap(quotes[i])['rentals']))
                    ListRow(label: '${r['name']} ×${r['quantity']}', value: money('${r['price']}', currency)),
                ],
              ],
              if (total != null) ListRow(label: 'Total', value: money(total, currency)),
            ]),
            if (trip.rent.isNotEmpty) const FootnoteText('Rentables are subject to the club’s approval.'),
          ],
        );
      },
    );
  }
}

/// pass_v1's "Booked" hero after BOOK-7, for one booking or several made together.
class BookedScreen extends StatelessWidget {
  const BookedScreen({super.key, required this.ids});
  final List<int> ids;

  @override
  Widget build(BuildContext context) => PassScaffold(
        title: 'Booked',
        back: '/book',
        children: [
          ApiLoader<List<Map<String, dynamic>>>(
            load: () async => [for (final id in ids) asMap(await _api.get('/api/sessions/$id/'))],
            builder: (context, all, _) {
              if (all.isEmpty) return const EmptyText('Nothing booked here.');
              final s = all.first;
              final court = asMap(s['court']);
              final where = '${court['name']}, ${asMap(court['club'])['name']}.';
              final starts = [for (final x in all) at('${x['starts_at']}')];
              final rentals = all.any((x) => asMaps(x['rentals']).isNotEmpty);
              return BookedBody(
                kicker: 'Booked',
                headline: all.length == 1
                    ? '${asMap(s['sport'])['name']}, ${dayLabel(starts.first)} ${hm(starts.first)}.\n$where'
                    : '${asMap(s['sport'])['name']}, ${_plural(all.length, 'session')}.\n$where',
                body: [
                  if (all.length > 1) ...starts.map((t) => '${dayLabel(t)} ${hm(t)}'),
                  rentals ? 'The court is yours. Your rentables wait for the club’s approval.' : 'The court is yours.',
                ].join('\n'),
                seeLabel: all.length == 1 ? 'See session' : 'See sessions',
                seePath: all.length == 1 ? '/sessions/${s['id']}' : '/sessions',
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
