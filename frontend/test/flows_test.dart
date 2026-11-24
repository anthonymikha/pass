import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pass/api.dart';
import 'package:pass/screens/player.dart';
import 'package:pass/screens/sessions.dart';
import 'package:timezone/data/latest.dart' as tzdata;

/// Fake backend: answers by "METHOD path" and records what was sent.
final sent = <String, Map>{};

void fake(Map<String, Object> answers) {
  sent.clear();
  Api.instance.client = MockClient((req) async {
    final key = '${req.method} ${req.url.path}';
    if (req.body.isNotEmpty) sent[key] = jsonDecode(req.body) as Map;
    final answer = answers[key];
    if (answer == null) return http.Response('{"detail": "not faked: $key"}', 404);
    return http.Response(jsonEncode(answer), 200, headers: {'content-type': 'application/json'});
  });
}

Widget app(String location, List<RouteBase> routes) =>
    MaterialApp.router(routerConfig: GoRouter(initialLocation: location, routes: routes));

void main() {
  setUpAll(tzdata.initializeTimeZones);
  setUp(() {
    Api.instance.token = 't';
    Api.instance.me = {'id': 1, 'full_name': 'Pat', 'coach_rate': '30.00', 'coach_currency': 'USD'};
  });

  testWidgets('a player books a court with a rentable (BOOK-6, BOOK-7)', (tester) async {
    tester.view.physicalSize = const Size(800, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    fake({
      'GET /api/courts/1/': {
        'club': {'id': 1, 'name': 'Hoops', 'address': 'Hamra', 'timezone': 'Asia/Beirut', 'currency': 'USD'},
        'court': {
          'id': 1, 'name': 'Court 1', 'description': '', 'slot_minutes': 60,
          'sports': [{'id': 3, 'name': 'Basketball'}],
        },
        'rates': [{'id': 1, 'weekday': 0, 'start_time': '09:00:00', 'end_time': '00:00:00', 'price': '50.00'}],
        'equipment': {
          'included': [{'id': 8, 'name': 'Showers', 'quantity': 1, 'court': null, 'rental_price': null}],
          'rentable': [{'id': 9, 'name': 'Ball machine', 'quantity': 2, 'court': null, 'rental_price': '15.00'}],
        },
      },
      'GET /api/courts/1/slots/': [
        {'starts_at': '2030-01-07T07:00:00Z', 'ends_at': '2030-01-07T08:00:00Z', 'price': '50.00'},
        {'starts_at': '2030-01-07T08:00:00Z', 'ends_at': '2030-01-07T09:00:00Z', 'price': '50.00'},
      ],
      'POST /api/sessions/quote/': {
        'currency': 'USD', 'price': '100.00', 'offer': null, 'discount_amount': '0.00',
        'rentals': [{'equipment': 9, 'name': 'Ball machine', 'quantity': 1, 'price': '15.00'}],
        'court_amount': '115.00',
      },
      'POST /api/sessions/': {'id': 7},
    });
    await tester.pumpWidget(app('/courts/1', [
      GoRoute(path: '/courts/:id', builder: (_, s) => CourtScreen(id: int.parse(s.pathParameters['id']!))),
      GoRoute(path: '/sessions/:id', builder: (_, s) => Text('session ${s.pathParameters['id']}')),
    ]));
    await tester.pumpAndSettle();

    expect(find.text('Monday'), findsOneWidget);
    expect(find.textContaining('09:00–24:00'), findsOneWidget);
    expect(find.text('• Showers (1)'), findsOneWidget); // an amenity
    expect(find.textContaining('Ball machine · \$15.00 per booking'), findsOneWidget); // a rentable

    await tester.tap(find.byTooltip('More'));
    await tester.tap(find.textContaining('09:00–10:00'));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('10:00–11:00')); // two slots in a row
    await tester.pumpAndSettle();
    expect(find.text('Total \$115.00'), findsOneWidget);

    await tester.tap(find.widgetWithText(FilledButton, 'Book'));
    await tester.pumpAndSettle();
    expect(find.text('session 7'), findsOneWidget);
    expect(sent['POST /api/sessions/'], {
      'court': 1, 'sport': 3, 'starts_at': '2030-01-07T07:00:00Z', 'ends_at': '2030-01-07T09:00:00Z',
      'currency': 'USD', 'rentals': [{'equipment': 9, 'quantity': 1}],
    });
  });

  testWidgets('a coach confirms a request at their own venue, fee from the hourly rate (BOOK-21, FE-4)', (tester) async {
    tester.view.physicalSize = const Size(800, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final request = {
      'id': 5, 'kind': 'training', 'status': 'requested', 'court': null, 'sport': {'id': 3, 'name': 'Basketball'},
      'booked_by': {'id': 2, 'full_name': 'Sam'}, 'coach': {'id': 1, 'full_name': 'Pat'},
      'starts_at': '2030-01-07T16:00:00Z', 'ends_at': '2030-01-07T17:30:00Z',
    };
    fake({
      'GET /api/sessions/5/': request,
      'GET /api/clubs/': {'count': 0, 'results': []},
      'POST /api/sessions/5/confirm/': {...request, 'status': 'confirmed'},
    });
    await tester.pumpWidget(app('/s/confirm', [
      GoRoute(path: '/s', builder: (_, _) => const Text('session page'), routes: [
        GoRoute(path: 'confirm', builder: (_, _) => const ConfirmScreen(id: 5)),
      ]),
    ]));
    await tester.pumpAndSettle();

    expect(find.widgetWithText(TextField, '45.00'), findsOneWidget); // 30 USD/hour × 1.5 h
    await tester.tap(find.widgetWithText(FilledButton, 'Confirm training'));
    await tester.pumpAndSettle();
    expect(sent['POST /api/sessions/5/confirm/'], {
      'starts_at': '2030-01-07T16:00:00.000Z', 'ends_at': '2030-01-07T17:30:00.000Z', 'currency': 'USD', 'coach_fee': '45.00',
    });
    expect(find.text('session page'), findsOneWidget);
  });
}
