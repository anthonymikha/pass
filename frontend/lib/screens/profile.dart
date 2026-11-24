import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

/// Own profile (ACC: /api/me/): name, phone, timezone, coach details (FE-4: rate per hour, USD), log out, delete.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final me = Api.instance.me!;
  late final name = TextEditingController(text: me['full_name']),
      phone = TextEditingController(text: me['phone']),
      bio = TextEditingController(text: me['coach_bio']),
      rate = TextEditingController(text: me['coach_rate'] ?? '');
  late String zone = me['timezone'];
  late bool coach = me['is_coach'];

  Future<void> _save() => act(context, () async {
        await Api.instance.patch('me/', {
          'full_name': name.text.trim(),
          'phone': phone.text.trim(),
          'timezone': zone.trim(),
          'is_coach': coach,
          if (coach) ...{
            'coach_bio': bio.text.trim(),
            'coach_rate': rate.text.trim().isEmpty ? null : rate.text.trim(),
            'coach_currency': 'USD', // FE-3
          },
        });
        await Api.instance.refreshMe();
      }, done: 'Saved.');

  Future<void> _delete() async {
    final password = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete account'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Your upcoming sessions are cancelled and your personal data is removed. This cannot be undone.'),
          TextField(controller: password, obscureText: true, decoration: const InputDecoration(labelText: 'Password')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep it')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Theme.of(c).colorScheme.error),
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) await act(context, () => Api.instance.deleteAccount(password.text));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Profile')),
        body: Body(children: [
          Text(me['email'], style: Theme.of(context).textTheme.bodySmall),
          TextField(controller: name, decoration: const InputDecoration(labelText: 'Full name')),
          TextField(controller: phone, decoration: const InputDecoration(labelText: 'Phone'), keyboardType: TextInputType.phone),
          TimezoneField(initial: zone, onChanged: (v) => zone = v),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('I am a coach'),
            subtitle: const Text('Players can find you and ask for training'),
            value: coach,
            onChanged: (v) => setState(() => coach = v),
          ),
          if (coach) ...[
            TextField(controller: bio, decoration: const InputDecoration(labelText: 'About you'), maxLines: 3),
            TextField(
              controller: rate,
              decoration: const InputDecoration(
                  labelText: 'Rate per hour (USD)', helperText: 'A guide: you set the fee when you confirm each session'),
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
            ),
          ],
          const SizedBox(height: 24),
          FilledButton(onPressed: _save, child: const Text('Save')),
          const SizedBox(height: 32),
          OutlinedButton(onPressed: Api.instance.logout, child: const Text('Log out')),
          TextButton(onPressed: _delete, child: const Text('Delete account')),
        ]),
      );
}
