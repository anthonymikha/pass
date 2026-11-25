// Welcome, sign up, sign in and forgot password (mvp.md, Everyone). Same layout as pass_v1's auth screens,
// without Sign in with Apple (not in the MVP).
import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../theme/tokens.dart';
import '../../widgets/alerts.dart';
import '../../widgets/controls.dart';
import '../../widgets/layout.dart';
import 'auth_scaffold.dart';

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AuthScaffold(
      bottomAligned: true,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: PassSpace.xxl),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('PASS', style: PassText.wordmark.copyWith(color: c.tint)),
            const SizedBox(height: PassSpace.ml),
            Text('Book a court, train with your coach, run your club.',
                style: PassText.title1.copyWith(color: c.label, height: 34 / 28, letterSpacing: 0)),
            const SizedBox(height: PassSpace.ml),
            Text('See prices and free times, book in a few taps.', style: PassText.body.copyWith(color: c.label2)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(PassSpace.gutter, PassSpace.xxxl, PassSpace.gutter, 0),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            PassButton('Create account', margin: EdgeInsets.zero, onPressed: () => context.push('/signup')),
            const SizedBox(height: PassSpace.m),
            PassButton('Sign in',
                kind: PassButtonKind.fill, margin: EdgeInsets.zero, onPressed: () => context.push('/signin')),
          ]),
        ),
      ],
    );
  }
}

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  final _email = TextEditingController();
  final _pass = TextEditingController();
  bool _busy = false;

  bool get _ok => _email.text.trim().isNotEmpty && _pass.text.isNotEmpty;

  @override
  void dispose() {
    _email.dispose();
    _pass.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_ok || _busy) return;
    setState(() => _busy = true);
    try {
      await AppState.instance.login(_email.text.trim(), _pass.text);
      // The router redirects to Book once signed in.
    } on ApiException catch (e) {
      if (mounted) await showErrorAlert(context, e, title: 'Sign in failed');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AuthScaffold(
        back: '/welcome',
        children: [
          const AuthHeader('Sign in', 'Welcome back.'),
          GroupedCard(
            inset: 0,
            margin: authButtonMargin(PassSpace.xxl),
            children: [
              FormFieldRow(
                  controller: _email,
                  placeholder: 'Email',
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  textInputAction: TextInputAction.next,
                  onChanged: (_) => setState(() {})),
              FormFieldRow(
                  controller: _pass,
                  placeholder: 'Password',
                  obscure: true,
                  autofillHints: const [AutofillHints.password],
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (_) => _submit()),
            ],
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(36, PassSpace.m, 0, 0),
              child: PassLink('Forgot password?',
                  padding: const EdgeInsets.symmetric(vertical: PassSpace.s), onTap: () => context.push('/forgot')),
            ),
          ),
          PassButton('Sign in', margin: authButtonMargin(PassSpace.gutter), enabled: _ok, busy: _busy, onPressed: _submit),
        ],
      );
}

class SignUpScreen extends StatefulWidget {
  const SignUpScreen({super.key});

  @override
  State<SignUpScreen> createState() => _SignUpScreenState();
}

class _SignUpScreenState extends State<SignUpScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _pass = TextEditingController();
  bool _busy = false;

  bool get _ok => _name.text.trim().isNotEmpty && _email.text.trim().isNotEmpty && _pass.text.length >= 8;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _pass.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_ok || _busy) return;
    setState(() => _busy = true);
    try {
      await AppState.instance.register(_name.text.trim(), _email.text.trim(), _pass.text);
    } on ApiException catch (e) {
      if (mounted) await showErrorAlert(context, e, title: 'Sign up failed');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final short = _pass.text.isNotEmpty && _pass.text.length < 8;
    return AuthScaffold(
      back: '/welcome',
      children: [
        const AuthHeader('Create account', 'It takes a minute. You can add the rest later.'),
        GroupedCard(
          inset: 0,
          margin: authButtonMargin(PassSpace.xxl),
          children: [
            FormFieldRow(
                controller: _name,
                placeholder: 'Full name',
                autofillHints: const [AutofillHints.name],
                textInputAction: TextInputAction.next,
                onChanged: (_) => setState(() {})),
            FormFieldRow(
                controller: _email,
                placeholder: 'Email',
                keyboardType: TextInputType.emailAddress,
                autofillHints: const [AutofillHints.email],
                textInputAction: TextInputAction.next,
                onChanged: (_) => setState(() {})),
            FormFieldRow(
                controller: _pass,
                placeholder: 'Password',
                obscure: true,
                autofillHints: const [AutofillHints.newPassword],
                textInputAction: TextInputAction.done,
                onChanged: (_) => setState(() {}),
                onSubmitted: (_) => _submit()),
          ],
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(36, PassSpace.sm, 36, 0),
          child: Text('Use at least 8 characters.',
              style: PassText.footnote.copyWith(color: short ? c.tintInk : c.label2)),
        ),
        PassButton('Continue', margin: authButtonMargin(PassSpace.xxl), enabled: _ok, busy: _busy, onPressed: _submit),
        const SizedBox(height: PassSpace.sm),
        Center(
          child: Pressable(
            onTap: () => context.go('/signin'),
            child: Padding(
              padding: const EdgeInsets.all(PassSpace.sm),
              child: Text.rich(
                TextSpan(text: 'Already have an account? ', children: [
                  TextSpan(text: 'Sign in', style: TextStyle(color: c.tint, fontWeight: PassText.semibold)),
                ]),
                style: PassText.subhead.copyWith(color: c.label2),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// ACC-32: sends the reset link; the new password is set on the backend's own page.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _email = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_email.text.trim().isEmpty || _busy) return;
    setState(() => _busy = true);
    try {
      await ApiClient.instance.post('/api/auth/password-reset/', body: {'email': _email.text.trim()});
      if (!mounted) return;
      await showPassAlert(context,
          title: 'Check your email',
          message: 'If an account uses this email, a link to set a new password is on its way. It works for one hour.',
          actions: const [AlertAction('OK', kind: AlertKind.primary)]);
      if (mounted) context.go('/signin');
    } on ApiException catch (e) {
      if (mounted) await showErrorAlert(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AuthScaffold(
        back: '/signin',
        children: [
          const AuthHeader('Forgot password', 'We email you a link to set a new one.'),
          GroupedCard(
            inset: 0,
            margin: authButtonMargin(PassSpace.xxl),
            children: [
              FormFieldRow(
                  controller: _email,
                  placeholder: 'Email',
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (_) => _submit()),
            ],
          ),
          PassButton('Send link',
              margin: authButtonMargin(PassSpace.xxl),
              enabled: _email.text.trim().isNotEmpty,
              busy: _busy,
              onPressed: _submit),
        ],
      );
}
