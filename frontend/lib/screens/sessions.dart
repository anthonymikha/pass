import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api.dart';
import '../widgets.dart';

String sessionTitle(Map s) {
  final me = Api.instance.myId;
  if (s['kind'] == 'training') {
    final coach = s['coach'];
    if (coach != null && coach['id'] == me) return 'Training: ${s['booked_by']['full_name']}';
    return 'Training with ${coach?['full_name'] ?? 'a coach'}';
  }
  return s['court'] == null ? 'Session' : '${s['court']['name']} · ${s['court']['club']['name']}';
}

class StatusChip extends StatelessWidget {
  const StatusChip(this.status, {super.key});
  final String status;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = switch (status) {
      'confirmed' => scheme.primary,
      'requested' || 'approved' => scheme.tertiary,
      'cancelled' || 'declined' => scheme.error,
      _ => scheme.outline,
    };
    return Text(status.toUpperCase(),
        style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 12, letterSpacing: 1));
  }
}

/// My sessions (BOOK-66). A coach sees the training requests waiting for an answer first.
class SessionsScreen extends StatefulWidget {
  const SessionsScreen({super.key});

  @override
  State<SessionsScreen> createState() => _SessionsScreenState();
}

class _SessionsScreenState extends State<SessionsScreen> {
  bool past = false;
  int version = 0; // bumped to reload after acting on a session

  Future<List<Map<String, dynamic>>> _load() async {
    final now = DateTime.now().toUtc();
    if (past) {
      // ponytail: the last 90 days, newest first; add paging when someone needs older sessions.
      final rows = await Api.instance.rows('me/sessions/',
          {'from': now.subtract(const Duration(days: 90)).toIso8601String(), 'to': now.toIso8601String()});
      return rows.where((s) => DateTime.parse(s['ends_at']).isBefore(now)).toList().reversed.toList();
    }
    final rows = await Api.instance.rows('me/sessions/', {'from': now.subtract(const Duration(days: 1)).toIso8601String()});
    return rows.where((s) => DateTime.parse(s['ends_at']).isAfter(now)).toList();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('My sessions')),
        body: Loaded(
          key: ValueKey('$past$version'),
          load: _load,
          builder: (context, rows, reload) {
            final me = Api.instance.myId;
            final toAnswer = rows.where((s) => s['status'] == 'requested' && s['coach']?['id'] == me).toList();
            final rest = rows.where((s) => !toAnswer.contains(s)).toList();
            return RefreshIndicator(
              onRefresh: () async => reload(),
              child: Body(children: [
                SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(value: false, label: Text('Upcoming')),
                    ButtonSegment(value: true, label: Text('Past')),
                  ],
                  selected: {past},
                  onSelectionChanged: (v) => setState(() => past = v.first),
                ),
                if (toAnswer.isNotEmpty) ...[
                  const Heading('Training requests to answer'),
                  for (final s in toAnswer) _tile(context, s),
                ],
                if (toAnswer.isNotEmpty) const Heading('Sessions'),
                if (rows.isEmpty)
                  Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(past ? 'No past sessions.' : 'Nothing booked yet. Find a court or a coach.',
                        textAlign: TextAlign.center),
                  ),
                for (final s in rest) _tile(context, s),
              ]),
            );
          },
        ),
      );

  Widget _tile(BuildContext context, Map s) => Card(
        child: ListTile(
          title: Text(sessionTitle(s)),
          subtitle: Text('${when(s['starts_at'])} · ${s['sport']['name']}'),
          trailing: StatusChip(s['status']),
          onTap: () async {
            await context.push('/sessions/${s['id']}');
            if (mounted) setState(() => version++);
          },
        ),
      );
}

/// One session (BOOK-65) with the actions the caller may take on it.
class SessionScreen extends StatelessWidget {
  const SessionScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Session')),
        body: Loaded(
          load: () async => (await Api.instance.get('sessions/$id/') as Map).cast<String, dynamic>(),
          builder: (context, s, reload) {
            final me = Api.instance.myId;
            final cur = s['currency'] as String?;
            final started = DateTime.parse(s['starts_at']).isBefore(DateTime.now());
            final isBooker = s['booked_by']['id'] == me, isCoach = s['coach']?['id'] == me;
            final text = Theme.of(context).textTheme;

            Future<void> post(String action, String done) async {
              if (await act(context, () => Api.instance.post('sessions/$id/$action/'), done: done)) reload();
            }

            return Body(children: [
              Row(children: [Expanded(child: Text(sessionTitle(s), style: text.headlineSmall)), StatusChip(s['status'])]),
              const SizedBox(height: 8),
              Text('${when(s['starts_at'])} – ${hm(DateTime.parse(s['ends_at']).toLocal())}'),
              Text(s['sport']['name']),
              if (s['court'] != null)
                Text('${s['court']['name']}, ${s['court']['club']['name']}')
              else if (s['kind'] == 'training' && s['status'] == 'confirmed')
                const Text("At the coach's venue"),
              if (s['coach'] != null) Text('Coach: ${s['coach']['full_name']}'),
              Text('Booked by ${s['booked_by']['full_name']}'),
              if (s['status'] == 'requested')
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(isCoach
                      ? 'Proposed time. Confirm it (or another time) with your fee and an optional court.'
                      : 'Waiting for the coach to confirm.'),
                ),
              if (cur != null && cur.isNotEmpty) ...[
                const Heading('Money'),
                if (s['court'] != null) Text('Court: ${money(s['price'], cur)}'),
                if (num.parse('${s['discount_amount']}') > 0) Text('Reduction: −${money(s['discount_amount'], cur)}'),
                if (s['kind'] == 'training') Text('Coach fee: ${money(s['coach_fee'], cur)}'),
                Text('Paid in person.', style: text.bodySmall),
              ],
              if ((s['rentals'] as List).isNotEmpty) ...[
                const Heading('Rentables'),
                for (final r in s['rentals'])
                  Row(children: [
                    Expanded(child: Text('${r['equipment']['name']} × ${r['quantity']} · ${money(r['price'], cur)}')),
                    StatusChip(r['status']),
                  ]),
              ],
              const Heading('People'),
              for (final p in s['participants']) Text('${p['user']['full_name']} (${p['status']})'),
              const SizedBox(height: 24),
              if (s['status'] == 'requested' && isCoach && !started) ...[
                FilledButton(
                  onPressed: () async {
                    await context.push('/sessions/$id/confirm');
                    reload();
                  },
                  child: const Text('Confirm'),
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: () async {
                    if (await confirm(context, 'Decline this training request?')) await post('decline', 'Declined.');
                  },
                  child: const Text('Decline'),
                ),
              ],
              if (s['status'] == 'requested' && isBooker && !started)
                OutlinedButton(
                  onPressed: () async {
                    if (await confirm(context, 'Withdraw this request?')) await post('withdraw', 'Withdrawn.');
                  },
                  child: const Text('Withdraw request'),
                ),
              if (s['status'] == 'confirmed' && (isBooker || isCoach))
                OutlinedButton(
                  onPressed: () async {
                    if (await confirm(context, 'Cancel this session? Everyone on it is told.')) await post('cancel', 'Cancelled.');
                  },
                  child: const Text('Cancel session'),
                ),
            ]);
          },
        ),
      );
}

/// The coach confirms a training request (BOOK-21): time, fee (FE-4), optional court.
class ConfirmScreen extends StatelessWidget {
  const ConfirmScreen({super.key, required this.id});
  final int id;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Confirm training')),
        body: Loaded(
          load: () async => (await Api.instance.get('sessions/$id/') as Map).cast<String, dynamic>(),
          builder: (context, s, _) => _ConfirmForm(s),
        ),
      );
}

class _ConfirmForm extends StatefulWidget {
  const _ConfirmForm(this.s);
  final Map<String, dynamic> s;

  @override
  State<_ConfirmForm> createState() => _ConfirmFormState();
}

class _ConfirmFormState extends State<_ConfirmForm> {
  late DateTime start = DateTime.parse(widget.s['starts_at']).toLocal();
  late int minutes = DateTime.parse(widget.s['ends_at']).difference(DateTime.parse(widget.s['starts_at'])).inMinutes;
  late final fee = TextEditingController(text: _fee());
  bool feeEdited = false, atCourt = false, busy = false;
  Map<String, dynamic>? court; // court detail of the picked court
  String? slotStart, slotEnd;
  late Future<List<Map<String, dynamic>>> clubs = Api.instance.rows('clubs/', {'sport': '${widget.s['sport']['id']}'});

  String _fee() {
    final rate = Api.instance.me?['coach_rate'];
    return rate == null ? '' : (num.parse('$rate') * minutes / 60).toStringAsFixed(2);
  }

  void _times(DateTime s, int m) {
    setState(() {
      start = s;
      minutes = m;
      if (!feeEdited) fee.text = _fee();
    });
  }

  Future<void> _submit() async {
    final body = atCourt
        ? {
            'court': court!['court']['id'],
            'starts_at': slotStart,
            'ends_at': slotEnd,
            'currency': court!['club']['currency'],
          }
        : {
            'starts_at': start.toUtc().toIso8601String(),
            'ends_at': start.add(Duration(minutes: minutes)).toUtc().toIso8601String(),
            'currency': 'USD', // FE-3
          };
    setState(() => busy = true);
    final ok = await act(context, () => Api.instance.post('sessions/${widget.s['id']}/confirm/', {...body, 'coach_fee': fee.text.trim()}),
        done: 'Confirmed. The player is told.');
    if (!mounted) return;
    setState(() => busy = false);
    if (ok) context.pop();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.s;
    return Body(children: [
      Text('${s['booked_by']['full_name']} asks for ${s['sport']['name']} on ${when(s['starts_at'])} '
          '(${DateTime.parse(s['ends_at']).difference(DateTime.parse(s['starts_at'])).inMinutes} min).'),
      const SizedBox(height: 16),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('At a club court'),
        subtitle: const Text("Off: at your own venue, no court fee"),
        value: atCourt,
        onChanged: (v) => setState(() => atCourt = v),
      ),
      if (!atCourt)
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          OutlinedButton.icon(
            icon: const Icon(Icons.calendar_today, size: 18),
            label: Text(day(start)),
            onPressed: () async {
              final d = await showDatePicker(
                  context: context,
                  initialDate: start,
                  firstDate: DateTime.now(),
                  lastDate: DateTime.now().add(const Duration(days: 365)));
              if (d != null) _times(DateTime(d.year, d.month, d.day, start.hour, start.minute), minutes);
            },
          ),
          OutlinedButton.icon(
            icon: const Icon(Icons.schedule, size: 18),
            label: Text(hm(start)),
            onPressed: () async {
              final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(start));
              if (t != null) _times(DateTime(start.year, start.month, start.day, t.hour, t.minute), minutes);
            },
          ),
          DropdownButton<int>(
            value: [30, 45, 60, 90, 120, 180, 240].contains(minutes) ? minutes : null,
            hint: Text('$minutes min'),
            items: [for (final m in [30, 45, 60, 90, 120, 180, 240]) DropdownMenuItem(value: m, child: Text('$m min'))],
            onChanged: (v) => _times(start, v!),
          ),
        ]),
      if (atCourt) ...[
        FutureBuilder(
          future: clubs,
          builder: (context, snap) {
            if (snap.hasError) return Text('${snap.error}');
            if (!snap.hasData) return const LinearProgressIndicator();
            return DropdownButtonFormField<int>(
              initialValue: court?['court']['id'],
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Court'),
              items: [
                for (final c in snap.data!)
                  for (final ct in c['courts'])
                    DropdownMenuItem(value: ct['id'] as int, child: Text('${c['name']} · ${ct['name']}')),
              ],
              onChanged: (v) async {
                final d = (await Api.instance.get('courts/$v/') as Map).cast<String, dynamic>();
                setState(() {
                  court = d;
                  slotStart = slotEnd = null;
                });
              },
            );
          },
        ),
        const SizedBox(height: 8),
        if (court != null)
          SlotPicker(
            key: ValueKey(court!['court']['id']),
            detail: court!,
            initialDate: DateTime(start.year, start.month, start.day),
            onChanged: (a, b, _) {
              slotStart = a;
              slotEnd = b;
              if (a != null) {
                _times(DateTime.parse(a).toLocal(), DateTime.parse(b!).difference(DateTime.parse(a)).inMinutes);
              } else {
                setState(() {});
              }
            },
          ),
      ],
      const SizedBox(height: 16),
      TextField(
        controller: fee,
        decoration: InputDecoration(
          labelText: 'Your fee (USD)', // FE-3
          helperText: Api.instance.me?['coach_rate'] == null ? null : 'Your rate × hours; change it if you like',
        ),
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        onChanged: (_) => setState(() => feeEdited = true),
      ),
      const SizedBox(height: 24),
      FilledButton(
        onPressed: busy || (atCourt && slotStart == null) || fee.text.trim().isEmpty ? null : _submit,
        child: const Text('Confirm training'),
      ),
    ]);
  }
}
