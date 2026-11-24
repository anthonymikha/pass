import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../api.dart';
import '../widgets.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key, required this.mode});
  final String mode; // login, register, forgot

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final email = TextEditingController(), password = TextEditingController(), name = TextEditingController();
  bool busy = false;

  Future<void> _submit() async {
    setState(() => busy = true);
    final api = Api.instance;
    await act(
      context,
      () => switch (widget.mode) {
        'register' => api.register(email.text.trim(), password.text, name.text.trim()),
        'forgot' => api.post('auth/password-reset/', {'email': email.text.trim()}),
        _ => api.login(email.text.trim(), password.text),
      },
      done: widget.mode == 'forgot' ? 'If this email has an account, a reset link is on its way.' : null,
    );
    if (mounted) setState(() => busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final mode = widget.mode;
    final title = {'register': 'Create account', 'forgot': 'Reset password'}[mode] ?? 'Log in';
    return Scaffold(
      body: Body(maxWidth: 420, children: [
        const SizedBox(height: 48),
        Text('PASS',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.w900, color: Theme.of(context).colorScheme.primary, letterSpacing: 4)),
        Text('Book courts and coaches', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 32),
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 16),
        if (mode == 'register')
          TextField(
              controller: name,
              decoration: const InputDecoration(labelText: 'Full name'),
              textInputAction: TextInputAction.next),
        TextField(
          controller: email,
          decoration: const InputDecoration(labelText: 'Email'),
          keyboardType: TextInputType.emailAddress,
          autofillHints: const [AutofillHints.email],
          textInputAction: TextInputAction.next,
        ),
        if (mode != 'forgot')
          TextField(
            controller: password,
            decoration: const InputDecoration(labelText: 'Password'),
            obscureText: true,
            autofillHints: [mode == 'register' ? AutofillHints.newPassword : AutofillHints.password],
            onSubmitted: (_) => _submit(),
          ),
        const SizedBox(height: 24),
        FilledButton(onPressed: busy ? null : _submit, child: Text(mode == 'forgot' ? 'Send reset link' : title)),
        const SizedBox(height: 8),
        if (mode != 'login') TextButton(onPressed: () => context.go('/login'), child: const Text('Back to log in')),
        if (mode == 'login') ...[
          TextButton(onPressed: () => context.go('/register'), child: const Text('Create an account')),
          TextButton(onPressed: () => context.go('/forgot'), child: const Text('Forgot password?')),
        ],
      ]),
    );
  }
}
