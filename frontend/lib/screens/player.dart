import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api.dart';
import '../widgets.dart';

Future<List<Map<String, dynamic>>> sports() => Api.instance.rows('sports/'); // CLUB-36

/// Find a court: clubs by name and sport (CLUB-30), each with its active courts.
class CourtsScreen extends StatefulWidget {
  const CourtsScreen({super.key});

  @override
  State<CourtsScreen> createState() => _CourtsScreenState();
}

class _CourtsScreenState extends State<CourtsScreen> {
  String q = '';
  int? sport;
  late Future<List<Map<String, dynamic>>> clubs = _search();
  final sportList = sports();

  Future<List<Map<String, dynamic>>> _search() => Api.instance.rows('clubs/', {'q': q, 'sport': sport?.toString()});

  void _refresh() => setState(() => clubs = _search());

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Find a court')),
        body: Body(children: [
          TextField(
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Club name'),
            onSubmitted: (v) {
              q = v.trim();
              _refresh();
            },
          ),
          const SizedBox(height: 8),
          FutureBuilder(
            future: sportList,
            builder: (context, snap) => Wrap(spacing: 8, children: [
              for (final s in snap.data ?? <Map<String, dynamic>>[])
                ChoiceChip(
                  label: Text(s['name']),
                  selected: sport == s['id'],
                  onSelected: (on) {
                    sport = on ? s['id'] : null;
                    _refresh();
                  },
                ),
            ]),
          ),
          const SizedBox(height: 8),
          FutureBuilder(
            future: clubs,
            builder: (context, snap) {
              if (snap.hasError) return Text('${snap.error}');
              if (!snap.hasData) return const LinearProgressIndicator();
              if (snap.data!.isEmpty) return const Padding(padding: EdgeInsets.all(16), child: Text('No clubs found.'));
              return Column(children: [
                for (final c in snap.data!)
                  Card(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      ListTile(
                        title: Text(c['name'], style: const TextStyle(fontWeight: FontWeight.bold)),
                        subtitle: (c['address'] ?? '').isEmpty ? null : Text(c['address']),
                      ),
                      for (final court in c['courts'])
                        ListTile(
                          leading: const Icon(Icons.sports_tennis),
                          title: Text(court['name']),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => context.go('/courts/${court['id']}'),
                        ),
                    ]),
                  ),
              ]);
            },
          ),
        ]),
      );
}

/// Court detail (CLUB-31): prices, amenities, rentables; then free slots, quote and booking (BOOK-6, BOOK-7).
class CourtScreen extends StatelessWidget {
  const CourtScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Court')),
        body: Loaded(
          load: () async => (await Api.instance.get('courts/$id/') as Map).cast<String, dynamic>(),
          builder: (context, d, _) => _CourtBody(d),
        ),
      );
}

class _CourtBody extends StatefulWidget {
  const _CourtBody(this.d);
  final Map<String, dynamic> d;

  @override
  State<_CourtBody> createState() => _CourtBodyState();
}

class _CourtBodyState extends State<_CourtBody> {
  Map<String, dynamic> get d => widget.d;
  String? startsAt, endsAt;
  late int sport = d['court']['sports'][0]['id'];
  final qty = <int, int>{}; // rentable id -> quantity
  Map<String, dynamic>? quote;
  bool busy = false;

  Map<String, dynamic> _body() => {
        'court': d['court']['id'],
        'sport': sport,
        'starts_at': startsAt,
        'ends_at': endsAt,
        'currency': d['club']['currency'], // FE-3: USD clubs, base currency only
        'rentals': [
          for (final e in qty.entries)
            if (e.value > 0) {'equipment': e.key, 'quantity': e.value}
        ],
      };

  Future<void> _quote() async {
    if (startsAt == null) return setState(() => quote = null);
    try {
      final q = (await Api.instance.post('sessions/quote/', _body()) as Map).cast<String, dynamic>();
      if (mounted) setState(() => quote = q);
    } catch (e) {
      if (mounted) setState(() => quote = {'error': '$e'});
    }
  }

  Future<void> _book() async {
    setState(() => busy = true);
    Map? session;
    final ok = await act(context, () async => session = await Api.instance.post('sessions/', _body()), done: 'Booked.');
    if (!mounted) return;
    setState(() => busy = false);
    if (ok) context.go('/sessions/${session!['id']}');
  }

  @override
  Widget build(BuildContext context) {
    final club = d['club'], court = d['court'], currency = club['currency'] as String;
    final rates = (d['rates'] as List).cast<Map>();
    final included = d['equipment']['included'] as List, rentable = d['equipment']['rentable'] as List;
    final text = Theme.of(context).textTheme;
    return Body(children: [
      Text(court['name'], style: text.headlineSmall),
      Text([club['name'], club['address']].where((s) => '${s ?? ''}'.isNotEmpty).join(' · ')),
      if ('${court['description']}'.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(court['description'])),
      const SizedBox(height: 8),
      Wrap(spacing: 8, children: [for (final s in court['sports']) Chip(label: Text(s['name']))]),
      Heading('Prices (per ${court['slot_minutes']}-minute slot)'),
      if (rates.isEmpty) const Text('No opening hours yet.'),
      for (var w = 0; w < 7; w++)
        if (rates.any((r) => r['weekday'] == w))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: 110, child: Text(weekdays[w])),
              Expanded(
                child: Text([
                  for (final r in rates.where((r) => r['weekday'] == w))
                    '${clock(r['start_time'])}–${clock(r['end_time'], end: true)}  ${money(r['price'], currency)}'
                ].join('\n')),
              ),
            ]),
          ),
      const Heading('Amenities'),
      if (included.isEmpty) const Text('None listed.'),
      for (final e in included) Text('• ${e['name']} (${e['quantity']})'),
      const Heading('Rentables'),
      if (rentable.isEmpty) const Text('None.'),
      for (final e in rentable)
        Row(children: [
          Expanded(child: Text('${e['name']} · ${money(e['rental_price'], currency)} per booking')),
          IconButton(
            icon: const Icon(Icons.remove_circle_outline),
            tooltip: 'Fewer',
            onPressed: (qty[e['id']] ?? 0) > 0
                ? () {
                    setState(() => qty[e['id']] = qty[e['id']]! - 1);
                    _quote();
                  }
                : null,
          ),
          Text('${qty[e['id']] ?? 0}'),
          IconButton(
            icon: const Icon(Icons.add_circle_outline),
            tooltip: 'More',
            onPressed: (qty[e['id']] ?? 0) < e['quantity']
                ? () {
                    setState(() => qty[e['id']] = (qty[e['id']] ?? 0) + 1);
                    _quote();
                  }
                : null,
          ),
        ]),
      if (rentable.isNotEmpty) Text('The club approves rentables.', style: text.bodySmall),
      const Heading('Book'),
      if ((court['sports'] as List).length > 1)
        DropdownButtonFormField<int>(
          initialValue: sport,
          decoration: const InputDecoration(labelText: 'Sport'),
          items: [for (final s in court['sports']) DropdownMenuItem(value: s['id'] as int, child: Text(s['name']))],
          onChanged: (v) => setState(() => sport = v!),
        ),
      SlotPicker(
        detail: d,
        onChanged: (s, e, _) {
          startsAt = s;
          endsAt = e;
          _quote();
        },
      ),
      const SizedBox(height: 16),
      if (quote != null && quote!['error'] != null) Text(quote!['error'], style: TextStyle(color: Theme.of(context).colorScheme.error)),
      if (quote != null && quote!['error'] == null)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Court: ${money(quote!['price'], currency)}'),
              if (quote!['offer'] != null)
                Text('Offer: −${money(quote!['discount_amount'], currency)}  ${quote!['offer']['message']}'),
              for (final r in quote!['rentals']) Text('${r['name']} × ${r['quantity']}: ${money(r['price'], currency)}'),
              const Divider(),
              Text('Total ${money(quote!['court_amount'], currency)}', style: text.titleMedium),
              Text('Paid at the club.', style: text.bodySmall),
            ]),
          ),
        ),
      const SizedBox(height: 8),
      FilledButton(
        onPressed: startsAt == null || busy || quote?['error'] != null ? null : _book,
        child: const Text('Book'),
      ),
    ]);
  }
}

/// Coach search (ACC-22) with each coach's rate.
class CoachesScreen extends StatefulWidget {
  const CoachesScreen({super.key});

  @override
  State<CoachesScreen> createState() => _CoachesScreenState();
}

class _CoachesScreenState extends State<CoachesScreen> {
  late Future<List<Map<String, dynamic>>> coaches = Api.instance.rows('coaches/');

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Find a coach')),
        body: Body(children: [
          TextField(
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Coach name'),
            onSubmitted: (v) => setState(() => coaches = Api.instance.rows('coaches/', {'q': v.trim()})),
          ),
          const SizedBox(height: 8),
          FutureBuilder(
            future: coaches,
            builder: (context, snap) {
              if (snap.hasError) return Text('${snap.error}');
              if (!snap.hasData) return const LinearProgressIndicator();
              if (snap.data!.isEmpty) return const Padding(padding: EdgeInsets.all(16), child: Text('No coaches found.'));
              return Column(children: [
                for (final c in snap.data!)
                  Card(
                    child: ListTile(
                      leading: CircleAvatar(child: Text(c['full_name'].toString().characters.first)),
                      title: Text(c['full_name']),
                      subtitle: Text(rate(c)),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => context.go('/coaches/${c['id']}'),
                    ),
                  ),
              ]);
            },
          ),
        ]),
      );
}

/// FE-4: the coach rate is per hour.
String rate(Map c) => c['coach_rate'] == null ? 'Rate on request' : '${money(c['coach_rate'], c['coach_currency'] ?? 'USD')} / hour';

/// A coach's public profile (ACC-21) and the training request (BOOK-20).
class CoachScreen extends StatefulWidget {
  const CoachScreen({super.key, required this.id});
  final int id;

  @override
  State<CoachScreen> createState() => _CoachScreenState();
}

class _CoachScreenState extends State<CoachScreen> {
  int? sport;
  DateTime date = DateTime.now().add(const Duration(days: 1));
  TimeOfDay start = const TimeOfDay(hour: 18, minute: 0);
  int minutes = 60;
  bool busy = false;

  Future<void> _request() async {
    final s = DateTime(date.year, date.month, date.day, start.hour, start.minute);
    setState(() => busy = true);
    Map? session;
    final ok = await act(
      context,
      () async => session = await Api.instance.post('training-requests/', {
        'coach': widget.id,
        'sport': sport,
        'starts_at': s.toUtc().toIso8601String(),
        'ends_at': s.add(Duration(minutes: minutes)).toUtc().toIso8601String(),
      }),
      done: 'Request sent. The coach confirms or proposes another time.',
    );
    if (!mounted) return;
    setState(() => busy = false);
    if (ok) context.go('/sessions/${session!['id']}');
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Coach')),
        body: Loaded(
          load: () async => [await Api.instance.get('users/${widget.id}/'), await sports()],
          builder: (context, data, _) {
            final c = data[0] as Map, sportList = data[1] as List;
            final text = Theme.of(context).textTheme;
            return Body(children: [
              Text(c['full_name'], style: text.headlineSmall),
              Text(rate(c), style: text.titleMedium),
              if ('${c['coach_bio'] ?? ''}'.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(c['coach_bio'])),
              if ((c['clubs'] as List? ?? []).isNotEmpty) Text('Coaches at ${(c['clubs'] as List).map((x) => x['name']).join(', ')}'),
              if (c['id'] != Api.instance.myId) ...[
                const Heading('Request training'),
                Text('Propose a time. The coach confirms it, or another time, with the fee and the court.', style: text.bodySmall),
                const SizedBox(height: 8),
                DropdownButtonFormField<int>(
                  initialValue: sport,
                  decoration: const InputDecoration(labelText: 'Sport'),
                  items: [for (final s in sportList) DropdownMenuItem(value: s['id'] as int, child: Text(s['name']))],
                  onChanged: (v) => setState(() => sport = v),
                ),
                const SizedBox(height: 8),
                Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  OutlinedButton.icon(
                    icon: const Icon(Icons.calendar_today, size: 18),
                    label: Text(day(date)),
                    onPressed: () async {
                      final d = await showDatePicker(
                          context: context,
                          initialDate: date,
                          firstDate: DateTime.now(),
                          lastDate: DateTime.now().add(const Duration(days: 365)));
                      if (d != null) setState(() => date = d);
                    },
                  ),
                  OutlinedButton.icon(
                    icon: const Icon(Icons.schedule, size: 18),
                    label: Text(start.format(context)),
                    onPressed: () async {
                      final t = await showTimePicker(context: context, initialTime: start);
                      if (t != null) setState(() => start = t);
                    },
                  ),
                  DropdownButton<int>(
                    value: minutes,
                    items: [for (final m in [60, 90, 120, 180]) DropdownMenuItem(value: m, child: Text('${(m / 60).toStringAsFixed(m % 60 == 0 ? 0 : 1)} h'))],
                    onChanged: (v) => setState(() => minutes = v!),
                  ),
                ]),
                const SizedBox(height: 16),
                FilledButton(onPressed: sport == null || busy ? null : _request, child: const Text('Send request')),
              ],
            ]);
          },
        ),
      );
}
