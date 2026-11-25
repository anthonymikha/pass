// Sessions tab (FE-10): my sessions, a coach's training requests (FE-8), a session's details with cancel,
// withdraw and decline, and the coach's confirm screen (BOOK-21, FE-4). Personal times use the device's time zone.
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
int? get _meId => AppState.instance.me?.id;

const _statusLabels = {
  'requested': 'Requested',
  'confirmed': 'Confirmed',
  'cancelled': 'Cancelled',
  'completed': 'Completed',
};

Widget statusPill(BuildContext context, String status) {
  final c = context.c;
  final (fg, bg) = switch (status) {
    'confirmed' => (c.tint, c.tintBg),
    'requested' => (c.label, c.fill2),
    _ => (c.label2, c.fill),
  };
  return TagPill(_statusLabels[status] ?? status, fg: fg, bg: bg);
}

/// "Padel · Court 1, Hoops" or "Training · Padel with Kim".
String sessionTitle(Map<String, dynamic> s) {
  final sport = '${asMap(s['sport'])['name']}';
  if (s['kind'] == 'training') {
    final coach = s['coach'] as Map<String, dynamic>?;
    return coach == null || coach['id'] == _meId
        ? 'Training · $sport with ${asMap(s['booked_by'])['full_name']}'
        : 'Training · $sport with ${coach['full_name']}';
  }
  final court = s['court'] as Map<String, dynamic>?;
  return court == null ? sport : '$sport · ${court['name']}, ${asMap(court['club'])['name']}';
}

bool _isRequestToMe(Map<String, dynamic> s) =>
    s['status'] == 'requested' && (s['coach'] as Map<String, dynamic>?)?['id'] == _meId;

class SessionsScreen extends StatefulWidget {
  const SessionsScreen({super.key});

  @override
  State<SessionsScreen> createState() => _SessionsScreenState();
}

class _SessionsScreenState extends State<SessionsScreen> {
  String _tab = 'upcoming';
  final _loader = GlobalKey<ApiLoaderState<List<dynamic>>>();

  /// Upcoming: starts from now, soonest first. Past: the 50 most recent, newest first (BOOK-66 lists oldest first).
  Future<List<dynamic>> _load() async {
    final now = iso(DateTime.now());
    if (_tab == 'upcoming') return _api.getAll('/api/me/sessions/', query: {'from': now});
    var page = asMap(await _api.get('/api/me/sessions/', query: {'to': now}));
    final count = page['count'] as int;
    if (count > 50) page = asMap(await _api.get('/api/me/sessions/', query: {'to': now, 'page': '${(count + 49) ~/ 50}'}));
    return (page['results'] as List).reversed.toList();
  }

  @override
  Widget build(BuildContext context) {
    final coach = AppState.instance.me?.isCoach == true;
    return PassScaffold(
      title: 'Sessions',
      onRefresh: () async {
        await _loader.currentState?.reload();
        await AppState.instance.refresh();
      },
      children: [
        const LargeTitleHeader(title: 'Sessions'),
        if (coach)
          ApiLoader<List<dynamic>>(
            key: ValueKey('requests-${AppState.instance.requestCount}'),
            load: () => _api.getAll('/api/me/sessions/', query: {'status': 'requested'}),
            builder: (context, data, _) {
              final mine = asMaps(data).where(_isRequestToMe).toList();
              return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                CapsHeader('Training requests · ${mine.length}'),
                if (mine.isEmpty)
                  const EmptyText('No requests waiting for you.')
                else
                  GroupedCard(inset: 0, children: [for (final s in mine) _row(context, s)]),
              ]);
            },
          ),
        PassSegmented<String>(
            values: const ['upcoming', 'past'],
            labelOf: (v) => v == 'upcoming' ? 'Upcoming' : 'Past',
            selected: _tab,
            onChanged: (v) => setState(() => _tab = v)),
        const SizedBox(height: PassSpace.ml),
        ApiLoader<List<dynamic>>(
          key: _loader,
          load: _load,
          builder: (context, data, _) {
            final list = asMaps(data).where((s) => !_isRequestToMe(s)).toList();
            if (list.isEmpty) {
              return EmptyText(_tab == 'upcoming' ? 'Nothing booked yet. Find a court or a coach in Book.' : 'No past sessions.');
            }
            return GroupedCard(inset: 0, children: [for (final s in list) _row(context, s)]);
          },
        ),
      ],
    );
  }

  Widget _row(BuildContext context, Map<String, dynamic> s) {
    final c = context.c;
    return Pressable(
      onTap: () => context.push('/sessions/${s['id']}'),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: PassSpace.card, vertical: PassSpace.m),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(sessionTitle(s), style: PassText.body.copyWith(color: c.label)),
              const SizedBox(height: PassSpace.xxs),
              Text(timeRange(at('${s['starts_at']}'), at('${s['ends_at']}')),
                  style: PassText.footnote.copyWith(color: c.label2)),
            ]),
          ),
          const SizedBox(width: PassSpace.sm),
          statusPill(context, '${s['status']}'),
          const SizedBox(width: PassSpace.sm),
          const Chevron(),
        ]),
      ),
    );
  }
}

const _rentalLabels = {'requested': 'waiting for the club', 'approved': 'approved', 'declined': 'declined'};

class SessionDetailScreen extends StatefulWidget {
  const SessionDetailScreen({super.key, required this.id});
  final int id;

  @override
  State<SessionDetailScreen> createState() => _SessionDetailScreenState();
}

class _SessionDetailScreenState extends State<SessionDetailScreen> {
  final _loader = GlobalKey<ApiLoaderState<Map<String, dynamic>>>();
  bool _busy = false;

  Future<void> _act(String action, String title, String message, String button) async {
    final ok = await showPassAlert(context, title: title, message: message, actions: [
      const AlertAction('Keep'),
      AlertAction(button, kind: AlertKind.destructive, value: 'go'),
    ]);
    if (ok != 'go' || !mounted) return;
    setState(() => _busy = true);
    try {
      await _api.post('/api/sessions/${widget.id}/$action/');
      await _loader.currentState?.reload();
      await AppState.instance.refresh();
    } on ApiException catch (e) {
      if (mounted) await showErrorAlert(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ApiLoader<Map<String, dynamic>>(
        key: _loader,
        load: () async => asMap(await _api.get('/api/sessions/${widget.id}/')),
        builder: (context, s, _) {
          final status = '${s['status']}';
          final court = s['court'] as Map<String, dynamic>?;
          final coach = s['coach'] as Map<String, dynamic>?;
          final booker = asMap(s['booked_by']);
          final cur = s['currency'] as String?;
          final rentals = asMaps(s['rentals']);
          final training = s['kind'] == 'training';
          final iAmCoach = coach?['id'] == _meId;
          final iAmBooker = booker['id'] == _meId;
          final hasDiscount = (double.tryParse('${s['discount_amount']}') ?? 0) > 0;
          // A request never confirmed has no currency (BOOK-20), so nothing is owed.
          final confirmedOnce = (cur ?? '').isNotEmpty;
          return PassScaffold(
            title: sessionTitle(s),
            back: '/sessions',
            children: [
              LargeTitleHeader(
                kicker: training ? 'Training' : 'Play',
                title: '${asMap(s['sport'])['name']}',
                subtitle: timeRange(at('${s['starts_at']}'), at('${s['ends_at']}')),
                trailing: statusPill(context, status),
              ),
              if (status == 'requested')
                NoticeBanner(
                    kind: NoticeKind.tint,
                    margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.ml, PassSpace.gutter, PassSpace.ml),
                    text: iAmCoach
                        ? 'Proposed time. Confirm it or another one, or decline.'
                        : 'Proposed time. The coach confirms it or another one.'),
              GroupedCard(inset: 0, children: [
                ListRow(
                    label: 'Court',
                    value: court != null
                        ? '${court['name']}, ${asMap(court['club'])['name']}'
                        : confirmedOnce
                            ? 'Coach’s own venue'
                            : 'Not set'),
                ListRow(label: 'Booker', value: '${booker['full_name']}'),
                if (coach != null) ListRow(label: 'Coach', value: '${coach['full_name']}'),
              ]),
              if (confirmedOnce) ...[
                const CapsHeader('What it costs'),
                GroupedCard(inset: 0, children: [
                  if (court != null) ListRow(label: 'Court price', value: money('${s['price']}', cur)),
                  if (hasDiscount) ListRow(label: 'Discount', value: '−${money('${s['discount_amount']}', cur)}'),
                  for (final r in rentals)
                    ListRow(
                        label: '${asMap(r['equipment'])['name']} ×${r['quantity']}',
                        value: '${money('${r['price']}', cur)} · ${_rentalLabels[r['status']] ?? r['status']}'),
                  if (training) ListRow(label: 'Coach fee', value: money('${s['coach_fee']}', cur)),
                ]),
                if (rentals.isNotEmpty) const FootnoteText('Rentables count only once the club approves them.'),
              ],
              if (status == 'requested' && iAmCoach) ...[
                PassButton('Confirm',
                    margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.xxl, PassSpace.gutter, 0),
                    onPressed: () => context.push('/sessions/${widget.id}/confirm')),
                PassButton('Decline',
                    kind: PassButtonKind.fill,
                    busy: _busy,
                    margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.m, PassSpace.gutter, 0),
                    onPressed: () => _act('decline', 'Decline this request?', 'The player is told.', 'Decline')),
              ],
              if (status == 'requested' && iAmBooker)
                PassButton('Withdraw request',
                    kind: PassButtonKind.fill,
                    busy: _busy,
                    margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.xxl, PassSpace.gutter, 0),
                    onPressed: () => _act('withdraw', 'Withdraw this request?', 'The coach is told.', 'Withdraw')),
              if (status == 'confirmed' && (iAmBooker || iAmCoach))
                PassButton('Cancel session',
                    kind: PassButtonKind.fill,
                    busy: _busy,
                    margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.xxl, PassSpace.gutter, 0),
                    onPressed: () => _act('cancel', 'Cancel this session?', 'The court is freed and everyone is told.', 'Cancel session')),
            ],
          );
        },
      );
}

/// BOOK-21: the coach confirms at the proposed time or another, with a fee (FE-4) and optionally a court.
class ConfirmTrainingScreen extends StatefulWidget {
  const ConfirmTrainingScreen({super.key, required this.id});
  final int id;

  @override
  State<ConfirmTrainingScreen> createState() => _ConfirmTrainingScreenState();
}

class _ConfirmTrainingScreenState extends State<ConfirmTrainingScreen> {
  final _fee = TextEditingController();
  bool _feeEdited = false;
  DateTime? _start, _end;
  bool _onCourt = false;
  final _clubQuery = TextEditingController();
  String _q = '';
  Map<String, dynamic>? _club; // search result
  Map<String, dynamic>? _court; // court detail (CLUB-31)
  SlotRun? _run;
  bool _busy = false;

  @override
  void dispose() {
    _fee.dispose();
    _clubQuery.dispose();
    super.dispose();
  }

  /// FE-4: coach rate × hours, until the coach types a fee of their own.
  void _setTimes(DateTime start, DateTime end) {
    _start = start;
    _end = end;
    final rate = AppState.instance.me?.coachRate;
    if (!_feeEdited && end.isAfter(start)) _fee.text = coachFee(rate ?? '0', end.difference(start).inMinutes, 'USD');
  }

  Future<void> _confirm() async {
    final withCourt = _onCourt && _court != null && _run != null;
    setState(() => _busy = true);
    try {
      await _api.post('/api/sessions/${widget.id}/confirm/', body: {
        'starts_at': withCourt ? _run!.startsAt : iso(_start!),
        'ends_at': withCourt ? _run!.endsAt : iso(_end!),
        'currency': withCourt ? asMap(_court!['club'])['currency'] : 'USD',
        'coach_fee': _fee.text.trim(),
        if (withCourt) 'court': asMap(_court!['court'])['id'],
      });
      await AppState.instance.refresh();
      if (!mounted) return;
      await showPassAlert(context,
          title: 'Confirmed',
          message: 'The player is told.',
          actions: const [AlertAction('OK', kind: AlertKind.primary)]);
      if (mounted) context.go('/sessions/${widget.id}');
    } on ApiException catch (e) {
      if (!mounted) return;
      await showErrorAlert(context, e,
          title: e.code == 'slot_taken' ? 'That court time was just taken' : 'Not confirmed');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ApiLoader<Map<String, dynamic>>(
        load: () async => asMap(await _api.get('/api/sessions/${widget.id}/')),
        builder: (context, s, _) {
          if (_start == null) _setTimes(at('${s['starts_at']}'), at('${s['ends_at']}'));
          final sport = asMap(s['sport']);
          final ready = _fee.text.trim().isNotEmpty &&
              (_onCourt ? _run != null : _end!.isAfter(_start!) && _start!.isAfter(DateTime.now()));
          return PassScaffold(
            title: 'Confirm',
            back: '/sessions/${widget.id}',
            children: [
              LargeTitleHeader(kicker: 'Training request', title: 'Confirm', subtitle: sessionTitle(s)),
              PassSegmented<bool>(
                  values: const [false, true],
                  labelOf: (v) => v ? 'On a court' : 'No court',
                  selected: _onCourt,
                  onChanged: (v) => setState(() => _onCourt = v)),
              if (!_onCourt) ...[
                const CapsHeader('Time'),
                GroupedCard(inset: 0, children: [
                  DateTimeRow(
                      label: 'Starts',
                      value: _start!,
                      onChanged: (v) => setState(() => _setTimes(v, v.add(_end!.difference(_start!))))),
                  DateTimeRow(label: 'Ends', value: _end!, onChanged: (v) => setState(() => _setTimes(_start!, v))),
                ]),
                const FootnoteText('Prefilled with the player’s proposal.'),
              ] else
                ..._courtPicker(context, sport),
              const CapsHeader('Coach fee'),
              GroupedCard(inset: 0, children: [
                FormFieldRow(
                    label: 'USD',
                    controller: _fee,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    onChanged: (_) => setState(() => _feeEdited = true)),
              ]),
              FootnoteText('Your coach rate × the hours: '
                  '${money(AppState.instance.me?.coachRate ?? '0', 'USD')} / hour. Change it if you like.'),
              PassButton('Confirm training',
                  margin: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.xxl, PassSpace.gutter, 0),
                  enabled: ready,
                  busy: _busy,
                  onPressed: _confirm),
            ],
          );
        },
      );

  /// Pick a club, one of its courts offering the session's sport, then a run of free slots.
  List<Widget> _courtPicker(BuildContext context, Map<String, dynamic> sport) {
    if (_court != null) {
      final club = asMap(_court!['club']);
      final court = asMap(_court!['court']);
      return [
        CapsHeader('${court['name']}, ${club['name']} · ${club['timezone']} time'),
        PassLink('Change court',
            padding: const EdgeInsets.fromLTRB(PassSpace.gutter, 0, PassSpace.gutter, PassSpace.sm),
            onTap: () => setState(() {
                  _court = null;
                  _run = null;
                })),
        SlotRunPicker(
            courtId: court['id'] as int,
            clubZone: '${club['timezone']}',
            currency: '${club['currency']}',
            onChanged: (run) => setState(() {
                  _run = run;
                  if (run != null) _setTimes(at(run.startsAt), at(run.endsAt));
                })),
      ];
    }
    if (_club != null) {
      return [
        CapsHeader('Courts at ${_club!['name']}'),
        PassLink('Change club',
            padding: const EdgeInsets.fromLTRB(PassSpace.gutter, 0, PassSpace.gutter, PassSpace.sm),
            onTap: () => setState(() => _club = null)),
        ApiLoader<List<dynamic>>(
          key: ValueKey('courts-${_club!['id']}'),
          load: () => _api.getAll('/api/clubs/${_club!['id']}/courts/'),
          builder: (context, data, _) {
            final courts = asMaps(data)
                .where((c) => c['is_active'] == true && (c['sports'] as List).contains(sport['id']))
                .toList();
            if (courts.isEmpty) return EmptyText('No court here offers ${sport['name']}.');
            return GroupedCard(inset: 0, children: [
              for (final c in courts)
                ListRow(
                    label: '${c['name']}',
                    trailing: const Chevron(),
                    onTap: () async {
                      try {
                        final d = asMap(await _api.get('/api/courts/${c['id']}/'));
                        setState(() => _court = d);
                      } on ApiException catch (e) {
                        if (context.mounted) await showErrorAlert(context, e);
                      }
                    }),
            ]);
          },
        ),
      ];
    }
    return [
      const CapsHeader('Club'),
      PassInput(
          controller: _clubQuery,
          placeholder: 'Search clubs by name',
          textInputAction: TextInputAction.search,
          onSubmitted: (v) => setState(() => _q = v.trim())),
      const SizedBox(height: PassSpace.ml),
      ApiLoader<List<dynamic>>(
        key: ValueKey('clubs-$_q'),
        load: () => _api.getAll('/api/clubs/', query: {'sport': '${sport['id']}', if (_q.isNotEmpty) 'q': _q}),
        builder: (context, data, _) {
          final clubs = asMaps(data);
          if (clubs.isEmpty) return EmptyText('No clubs with ${sport['name']} found.');
          return GroupedCard(inset: 0, children: [
            for (final cl in clubs)
              ListRow(label: '${cl['name']}', trailing: const Chevron(), onTap: () => setState(() => _club = cl)),
          ]);
        },
      ),
    ];
  }
}
