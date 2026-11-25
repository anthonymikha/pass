// Runs the real app (router, screens) with only the HTTP transport faked (package:http's MockClient).
import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pass_app/app.dart';
import 'package:pass_app/core/api_client.dart';
import 'package:pass_app/core/app_state.dart';

/// One request the app sent.
class Sent {
  Sent(this.method, this.path, this.query, this.body);
  final String method, path;
  final Map<String, String> query;
  final Object? body;
}

/// A fake backend: `routes['GET /api/me/']` answers that request (a value, or a function of the request).
class FakeApi {
  FakeApi(this.routes);
  final Map<String, Object? Function(Sent)> routes;
  final sent = <Sent>[];

  List<Sent> calls(String method, String path) => sent.where((s) => s.method == method && s.path == path).toList();

  late final client = MockClient((req) async {
    final s = Sent(req.method, req.url.path, req.url.queryParameters, req.body.isEmpty ? null : jsonDecode(req.body));
    sent.add(s);
    final handler = routes['${req.method} ${req.url.path}'];
    if (handler == null) return http.Response(jsonEncode({'detail': 'Not found.'}), 404);
    final out = handler(s);
    final (status, body) = out is (int, Object?) ? out : (200, out);
    return http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});
  });
}

/// A DRF page (GEN-12).
Map<String, Object?> page(List<Object?> results) => {'count': results.length, 'next': null, 'previous': null, 'results': results};

Map<String, Object?> meJson({int id = 1, String name = 'Pat Player', bool coach = false, String? rate}) => {
      'id': id, 'email': 'pat@example.com', 'full_name': name, 'phone': '', 'avatar': '', 'timezone': 'Asia/Beirut',
      'is_coach': coach, 'coach_bio': '', 'coach_rate': rate, 'coach_currency': coach ? 'USD' : null,
    };

/// Starts the app at [path], signed in as [me], against [api]. Phone size unless [size] says otherwise.
Future<void> startApp(WidgetTester tester, FakeApi api, String path,
    {required Map<String, Object?> me, List<Map<String, dynamic>> clubs = const [], Size size = const Size(390, 2400)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  ApiClient.instance = ApiClient(client: api.client);
  ApiClient.instance.token = 'test-token';
  AppState.instance.setMeForTest(me, clubs: clubs);
  await tester.pumpWidget(PassApp(initialLocation: path));
  await settle(tester);
}

/// Taps the widget showing [text] (scrolling it into view first).
Future<void> tapText(WidgetTester tester, String text, {int index = 0}) async {
  final f = find.text(text).at(index);
  await tester.ensureVisible(f);
  await settle(tester);
  await tester.tap(f);
  await settle(tester);
}

/// Taps the control with this semantics label ("Increase", "Slot 10:00", "Saturday").
Future<void> tapLabel(WidgetTester tester, String label, {int index = 0}) async {
  // A Pressable's label is followed by its child's text ("Slot 10:00\n10:00\n20.00 USD").
  final f = find.bySemanticsLabel(RegExp('^${RegExp.escape(label)}(\\s|\$)')).at(index);
  await tester.ensureVisible(f);
  await settle(tester);
  await tester.tap(f);
  await settle(tester);
}

/// Types into the text field whose placeholder is [placeholder] (or that currently holds [placeholder]).
Future<void> enter(WidgetTester tester, String placeholder, String text) async {
  final f = find.byWidgetPredicate(
      (w) => w is CupertinoTextField && (w.placeholder == placeholder || w.controller?.text == placeholder));
  await tester.ensureVisible(f.first);
  await tester.enterText(f.first, text);
  await settle(tester);
}

/// Lets requests answer and animations run for a second and a half of fake time. Not pumpAndSettle: a busy
/// button keeps its spinner turning while an alert is up.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 15; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}
