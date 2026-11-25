// Design alert: glass card r34, title 17 Semibold, message 15, two pill buttons side by side.
import 'package:flutter/cupertino.dart';
import 'package:flutter/services.dart';

import '../theme/tokens.dart';
import 'controls.dart';

enum AlertKind { cancel, primary, destructive }

class AlertAction {
  const AlertAction(this.label, {this.kind = AlertKind.cancel, this.value});
  final String label;
  final AlertKind kind;

  /// Returned from [showPassAlert] when tapped; defaults to [label].
  final String? value;
}

/// Shows an alert; returns the tapped action's value (or label), null when dismissed with Esc.
Future<String?> showPassAlert(BuildContext context,
    {required String title, String? message, List<AlertAction> actions = const [AlertAction('OK')]}) {
  return showCupertinoDialog<String>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => _PassAlert(title: title, message: message, actions: actions),
  );
}

/// Shorthand for an error alert.
Future<void> showErrorAlert(BuildContext context, Object error, {String title = 'Something went wrong'}) =>
    showPassAlert(context, title: title, message: '$error');

class _PassAlert extends StatelessWidget {
  const _PassAlert({required this.title, this.message, required this.actions});
  final String title;
  final String? message;
  final List<AlertAction> actions;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    Widget button(AlertAction a) {
      final (bg, fg) = switch (a.kind) {
        AlertKind.cancel => (c.fill2, c.label),
        AlertKind.primary => (c.tint, PassColors.white),
        AlertKind.destructive => (PassColors.destructive, PassColors.white),
      };
      return Pressable(
        onTap: () => Navigator.of(context).pop(a.value ?? a.label),
        child: Container(
          height: 48,
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(horizontal: PassSpace.m),
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(PassRadii.pill)),
          child: Text(a.label,
              textAlign: TextAlign.center,
              style: PassText.body.copyWith(
                  color: fg, fontWeight: a.kind == AlertKind.cancel ? PassText.regular : PassText.semibold)),
        ),
      );
    }

    return CallbackShortcuts(
      bindings: {const SingleActivator(LogicalKeyboardKey.escape): () => Navigator.of(context).pop()},
      child: Focus(
        autofocus: true,
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 44),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 300),
              child: Container(
                    padding: const EdgeInsets.fromLTRB(18, 22, 18, 18),
                    decoration: BoxDecoration(color: c.alertBg, borderRadius: BorderRadius.circular(PassRadii.alert)),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(title, textAlign: TextAlign.center, style: PassText.headline.copyWith(color: c.label)),
                      if (message != null) ...[
                        const SizedBox(height: PassSpace.s),
                        Text(message!,
                            textAlign: TextAlign.center, style: PassText.subhead.copyWith(color: c.label, height: 1.35)),
                      ],
                      const SizedBox(height: PassSpace.gutter),
                      if (actions.length == 2)
                        Row(children: [
                          Expanded(child: button(actions[0])),
                          const SizedBox(width: PassSpace.m),
                          Expanded(child: button(actions[1])),
                        ])
                      else
                        for (final a in actions)
                          Padding(padding: const EdgeInsets.only(top: 6), child: button(a)),
                    ]),
                  ),
            ),
          ),
        ),
      ),
    );
  }
}
