// Profile tab (FE-10): name, phone, time zone; "I am a coach" with bio and coach rate (FE-4, USD per hour);
// create a club (FE-3: base currency USD); log out (ACC-31); delete account (ACC-33).
import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/format.dart';
import '../../core/token_store.dart';
import '../../theme/tokens.dart';
import '../../widgets/alerts.dart';
import '../../widgets/controls.dart';
import '../../widgets/layout.dart';
import '../../widgets/scaffold.dart';
import '../shared.dart';

EdgeInsets get _buttonMargin => const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.lg, PassSpace.gutter, 0);

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final s = AppState.instance;
  late final _name = TextEditingController(text: s.me?.fullName);
  late final _phone = TextEditingController(text: s.me?.phone);
  late String _zone = s.me?.timezone ?? 'UTC';
  late bool _coach = s.me?.isCoach ?? false;
  late final _bio = TextEditingController(text: s.me?.coachBio);
  late final _rate = TextEditingController(text: s.me?.coachRate == null ? '' : money(s.me!.coachRate, 'USD').split(' ').first);
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _bio.dispose();
    _rate.dispose();
    super.dispose();
  }

  Future<void> _save(Map<String, Object?> fields, {String? done}) async {
    setState(() => _busy = true);
    try {
      await s.updateMe(fields);
      if (mounted && done != null) {
        await showPassAlert(context, title: done, actions: const [AlertAction('OK', kind: AlertKind.primary)]);
      }
    } on ApiException catch (e) {
      if (mounted) await showErrorAlert(context, e, title: 'Not saved');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final me = s.me;
    return PassScaffold(
      title: 'Profile',
      children: [
        LargeTitleHeader(title: me?.fullName ?? 'Profile', subtitle: me?.email),
        const CapsHeader('Profile'),
        GroupedCard(inset: 0, children: [
          FormFieldRow(label: 'Name', controller: _name),
          FormFieldRow(label: 'Phone', controller: _phone, placeholder: 'Optional', keyboardType: TextInputType.phone),
          PickerRow(label: 'Time zone', options: zoneNames(), value: _zone, onChanged: (v) => setState(() => _zone = v)),
        ]),
        PassButton('Save profile',
            kind: PassButtonKind.secondary,
            margin: _buttonMargin,
            busy: _busy,
            onPressed: () => _save({'full_name': _name.text.trim(), 'phone': _phone.text.trim(), 'timezone': _zone},
                done: 'Profile saved')),
        const CapsHeader('Coaching'),
        GroupedCard(inset: 0, children: [
          ListRow(
              label: 'I am a coach',
              trailing: PassSwitch(
                  value: _coach,
                  onChanged: (v) {
                    setState(() => _coach = v);
                    _save({'is_coach': v, if (v) 'coach_currency': 'USD'});
                  })),
          if (_coach) ...[
            FormFieldRow(label: 'Bio', controller: _bio, placeholder: 'What you coach'),
            FormFieldRow(
                label: 'Rate',
                controller: _rate,
                placeholder: 'USD per hour',
                keyboardType: const TextInputType.numberWithOptions(decimal: true)),
          ],
        ]),
        if (_coach) ...[
          const FootnoteText('Players see your rate as a guide: you set the coach fee of each session when you '
              'confirm it. USD per hour.'),
          PassButton('Save coaching',
              kind: PassButtonKind.secondary,
              margin: _buttonMargin,
              busy: _busy,
              onPressed: () => _save({
                    'coach_bio': _bio.text.trim(),
                    'coach_rate': _rate.text.trim().isEmpty ? null : _rate.text.trim(),
                    'coach_currency': 'USD',
                  }, done: 'Coaching saved')),
        ],
        const CapsHeader('Club'),
        GroupedCard(inset: 0, children: [
          ListRow(label: 'Create a club', trailing: const Chevron(), onTap: () => context.push('/profile/new-club')),
        ]),
        const CapsHeader('Account'),
        GroupedCard(inset: 0, children: [
          ListRow(label: 'Log out', labelColor: context.c.tint, onTap: s.logout),
          ListRow(
              label: 'Delete account',
              labelColor: PassColors.destructive,
              onTap: () => context.push('/profile/delete')),
        ]),
      ],
    );
  }
}

/// CLUB-1 with base currency USD (FE-3).
class NewClubScreen extends StatefulWidget {
  const NewClubScreen({super.key});

  @override
  State<NewClubScreen> createState() => _NewClubScreenState();
}

class _NewClubScreenState extends State<NewClubScreen> {
  final _name = TextEditingController();
  final _address = TextEditingController();
  late String _zone = _defaultZone();
  bool _busy = false;

  static String _defaultZone() {
    final names = zoneNames();
    final device = deviceTimeZone();
    if (device != null && names.contains(device)) return device;
    return AppState.instance.me?.timezone ?? 'UTC';
  }

  @override
  void dispose() {
    _name.dispose();
    _address.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    setState(() => _busy = true);
    try {
      final club = asMap(await ApiClient.instance.post('/api/clubs/',
          body: {'name': _name.text.trim(), 'address': _address.text.trim(), 'timezone': _zone, 'currency': 'USD'}));
      await AppState.instance.refresh();
      if (mounted) context.go('/club/${club['id']}/setup');
    } on ApiException catch (e) {
      if (mounted) await showErrorAlert(context, e, title: 'Club not created');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PassScaffold(
        title: 'New club',
        back: '/profile',
        children: [
          const LargeTitleHeader(title: 'New club', subtitle: 'You add courts, prices and equipment next.'),
          const SizedBox(height: PassSpace.ml),
          GroupedCard(inset: 0, children: [
            FormFieldRow(label: 'Name', controller: _name, placeholder: 'Club name', onChanged: (_) => setState(() {})),
            FormFieldRow(label: 'Address', controller: _address, placeholder: 'Optional'),
            PickerRow(label: 'Time zone', options: zoneNames(), value: _zone, onChanged: (v) => setState(() => _zone = v)),
          ]),
          const FootnoteText('Prices are in USD.'),
          PassButton('Create club',
              margin: _buttonMargin, enabled: _name.text.trim().isNotEmpty, busy: _busy, onPressed: _create),
        ],
      );
}

/// ACC-33: needs the password; refused while the user owns a club.
class DeleteAccountScreen extends StatefulWidget {
  const DeleteAccountScreen({super.key});

  @override
  State<DeleteAccountScreen> createState() => _DeleteAccountScreenState();
}

class _DeleteAccountScreenState extends State<DeleteAccountScreen> {
  final _pass = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _pass.dispose();
    super.dispose();
  }

  Future<void> _delete() async {
    setState(() => _busy = true);
    try {
      await AppState.instance.deleteAccount(_pass.text);
    } on ApiException catch (e) {
      if (mounted) {
        await showErrorAlert(context, e.code == 'owns_club' ? 'You own a club, so the account cannot be deleted.' : e,
            title: 'Not deleted');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PassScaffold(
        title: 'Delete account',
        back: '/profile',
        children: [
          const LargeTitleHeader(title: 'Delete account'),
          const NoticeBanner(
              kind: NoticeKind.tint,
              text: 'Your upcoming sessions are cancelled and your personal data is removed. This cannot be undone.'),
          GroupedCard(inset: 0, children: [
            FormFieldRow(
                controller: _pass, placeholder: 'Password', obscure: true, onChanged: (_) => setState(() {})),
          ]),
          PassButton('Delete my account',
              margin: _buttonMargin, enabled: _pass.text.isNotEmpty, busy: _busy, onPressed: _delete),
        ],
      );
}
