// The three MVP journeys (issue #1, Testing Decisions): the real screens and router, only HTTP faked.
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pass_app/core/app_state.dart';
import 'package:pass_app/core/format.dart';

import 'helpers.dart';

/// Free slots at 10:00, 11:00 and 12:00 Beirut time (UTC+2 in winter) on the asked date, 20 USD each.
Object slotsFor(Sent s) {
  final d = DateTime.parse(s.query['date']!);
  return [
    for (final h in [8, 9, 10])
      {
        'starts_at': iso(DateTime.utc(d.year, d.month, d.day, h)),
        'ends_at': iso(DateTime.utc(d.year, d.month, d.day, h + 1)),
        'price': '20.000',
      }
  ];
}

const club = {'id': 1, 'name': 'Hoops', 'address': 'Hamra', 'timezone': 'Asia/Beirut', 'currency': 'USD'};
const courtDetail = {
  'club': {...club, 'latitude': null, 'longitude': null, 'currencies': []},
  'court': {'id': 1, 'name': 'Court 1', 'description': 'Indoor', 'slot_minutes': 60, 'is_active': true,
    'sports': [{'id': 1, 'name': 'Padel'}]},
  'rates': [{'id': 1, 'weekday': 0, 'start_time': '09:00:00', 'end_time': '22:00:00', 'price': '20.000'}],
  'equipment': {
    'included': [{'id': 1, 'name': 'Showers', 'quantity': 1, 'court': null, 'rental_price': null}],
    'rentable': [{'id': 2, 'name': 'Rackets', 'quantity': 4, 'court': 1, 'rental_price': '5.000'}],
  },
};
const courtRow = {'id': 1, 'name': 'Court 1', 'description': 'Indoor', 'slot_minutes': 60, 'sports': [1], 'is_active': true};
const pat = {'id': 1, 'full_name': 'Pat Player', 'is_coach': false};
const kim = {'id': 2, 'full_name': 'Kim Coach', 'is_coach': true};

void main() {
  testWidgets('player finds a court, picks two slots and a rentable, sees the quote and books', (tester) async {
    final api = FakeApi({
      'GET /api/sports/': (_) => [{'id': 1, 'name': 'Padel'}],
      'GET /api/clubs/': (_) => page([{...club, 'distance_km': null, 'courts': [{'id': 1, 'name': 'Court 1'}]}]),
      'GET /api/clubs/1/': (_) => club,
      'GET /api/clubs/1/courts/': (_) => page([courtRow]),
      'GET /api/courts/1/': (_) => courtDetail,
      'GET /api/courts/1/slots/': slotsFor,
      'POST /api/sessions/quote/': (s) {
        final rentals = ((s.body as Map)['rentals'] as List).cast<Map>();
        final q = rentals.isEmpty ? 0 : rentals.first['quantity'] as int;
        return {
          'currency': 'USD', 'price': '40.000', 'offer': null, 'discount_amount': '0.000',
          'rentals': [if (q > 0) {'equipment': 2, 'name': 'Rackets', 'quantity': q, 'price': '${5 * q}.000'}],
          'court_amount': '${40 + 5 * q}.000',
        };
      },
      'POST /api/sessions/': (_) => (201, {'id': 9}),
      'GET /api/sessions/9/': (_) => {
            'id': 9, 'kind': 'play', 'status': 'confirmed', 'sport': {'id': 1, 'name': 'Padel'},
            'court': {'id': 1, 'name': 'Court 1', 'club': {'id': 1, 'name': 'Hoops'}}, 'booked_by': pat, 'coach': null,
            'starts_at': '2030-01-07T08:00:00Z', 'ends_at': '2030-01-07T10:00:00Z', 'currency': 'USD',
            'price': '40.000', 'discount_amount': '0.000', 'coach_fee': '0.000', 'participants': [],
            'rentals': [{'id': 3, 'equipment': {'id': 2, 'name': 'Rackets'}, 'quantity': 2, 'price': '10.000', 'status': 'requested'}],
          },
    });
    await startApp(tester, api, '/book', me: meJson());

    await tapText(tester, 'Hoops');
    await tapText(tester, 'Court 1');
    expect(find.text('Showers'), findsOneWidget); // amenity
    expect(find.text('09:00–22:00 · 20.00 USD'), findsOneWidget); // prices per weekday
    expect(find.text('Monday'), findsOneWidget);

    await tapLabel(tester, 'Slot 10:00');
    await tapLabel(tester, 'Slot 11:00');
    await tapLabel(tester, 'Increase');
    await tapLabel(tester, 'Increase');
    expect(find.text('Rackets ×2'), findsOneWidget); // quote line
    expect(find.text('50.00 USD'), findsOneWidget); // total
    expect(find.text('Rentables are subject to the club’s approval.'), findsOneWidget);

    await tapText(tester, 'Book · 50.00 USD');
    expect(find.text('Booked'), findsOneWidget);
    await tapText(tester, 'OK');

    final quote = api.calls('POST', '/api/sessions/quote/').last.body as Map;
    final booking = api.calls('POST', '/api/sessions/').single.body as Map;
    expect(booking, quote); // booked exactly what was quoted
    expect(booking['court'], 1);
    expect(booking['sport'], 1);
    expect(booking['currency'], 'USD');
    expect(booking['rentals'], [{'equipment': 2, 'quantity': 2}]);
    expect(DateTime.parse(booking['ends_at'] as String).difference(DateTime.parse(booking['starts_at'] as String)),
        const Duration(hours: 2));
    expect(find.textContaining('waiting for the club'), findsOneWidget); // the session, with its rental's status
  });

  testWidgets('coach confirms a request with the fee prefilled as rate × hours, on a court at another time',
      (tester) async {
    final request = {
      'id': 7, 'kind': 'training', 'status': 'requested', 'sport': {'id': 1, 'name': 'Padel'}, 'court': null,
      'booked_by': pat, 'coach': kim, 'starts_at': '2030-01-07T14:00:00Z', 'ends_at': '2030-01-07T15:30:00Z',
      'currency': null, 'price': '0.000', 'discount_amount': '0.000', 'coach_fee': '0.000', 'participants': [], 'rentals': [],
    };
    final api = FakeApi({
      'GET /api/me/clubs/': (_) => page([]),
      'GET /api/me/sessions/': (s) => page(s.query['status'] == 'requested' ? [request] : []),
      'GET /api/sessions/7/': (_) => request,
      'GET /api/clubs/': (_) => page([{...club, 'distance_km': null, 'courts': [{'id': 1, 'name': 'Court 1'}]}]),
      'GET /api/clubs/1/courts/': (_) => page([courtRow]),
      'GET /api/courts/1/': (_) => courtDetail,
      'GET /api/courts/1/slots/': slotsFor,
      'POST /api/sessions/7/confirm/': (_) => {...request, 'status': 'confirmed'},
    });
    await startApp(tester, api, '/sessions', me: meJson(id: 2, name: 'Kim Coach', coach: true, rate: '30.000'));
    AppState.instance.refresh();
    await settle(tester);
    expect(AppState.instance.requestCount, 1); // FE-8 badge
    expect(find.text('TRAINING REQUESTS · 1'), findsOneWidget);

    await tapText(tester, 'Training · Padel with Pat Player');
    expect(find.text('Proposed time. Confirm it or another one, or decline.'), findsOneWidget);
    await tapText(tester, 'Confirm');
    expect(find.text('45.00'), findsOneWidget); // 30 USD/hour × 1.5 hours (FE-4)

    await tapText(tester, 'On a court');
    await tapText(tester, 'Hoops');
    await tapText(tester, 'Court 1');
    await tapLabel(tester, 'Slot 10:00');
    await tapLabel(tester, 'Slot 11:00');
    expect(find.text('60.00'), findsOneWidget); // the fee follows the new time: 2 hours

    await tapText(tester, 'Confirm training');
    expect(find.text('Confirmed'), findsOneWidget);
    await tapText(tester, 'OK');
    final body = api.calls('POST', '/api/sessions/7/confirm/').single.body as Map;
    expect(body['coach_fee'], '60.00');
    expect(body['currency'], 'USD');
    expect(body['court'], 1);
    expect(body['starts_at'], endsWith('T08:00:00.000Z')); // 10:00 Beirut, not the proposed 16:00
    expect(body['ends_at'], endsWith('T10:00:00.000Z'));
  });

  testWidgets('club owner adds a court, a price window, an amenity and a rentable (desktop)', (tester) async {
    final courts = <Map<String, Object?>>[];
    final rates = <Map<String, Object?>>[];
    final items = <Map<String, Object?>>[];
    final api = FakeApi({
      'GET /api/me/clubs/': (_) => page([{...club, 'roles': ['owner']}]),
      'GET /api/clubs/1/': (_) => club,
      'GET /api/clubs/1/courts/': (_) => page(courts),
      'GET /api/sports/': (_) => [{'id': 1, 'name': 'Padel'}, {'id': 2, 'name': 'Tennis'}],
      'POST /api/clubs/1/courts/': (s) {
        courts.add({...(s.body as Map).cast<String, Object?>(), 'id': 5});
        return (201, courts.last);
      },
      'GET /api/courts/5/rates/': (_) => page(rates),
      'POST /api/courts/5/rates/': (s) {
        rates.add({...(s.body as Map).cast<String, Object?>(), 'id': rates.length + 1});
        return (201, rates.last);
      },
      'GET /api/clubs/1/equipment/': (_) => page(items),
      'POST /api/clubs/1/equipment/': (s) {
        items.add({...(s.body as Map).cast<String, Object?>(), 'id': items.length + 1});
        return (201, items.last);
      },
    });
    await startApp(tester, api, '/club/1/setup',
        me: meJson(id: 3, name: 'Olga Owner'),
        clubs: [{...club, 'roles': ['owner']}],
        size: const Size(1280, 2400));

    await tapText(tester, 'Add a court');
    await enter(tester, 'Court 1', 'Centre court');
    await tapText(tester, 'Padel');
    await tapText(tester, 'Add court');
    expect(api.calls('POST', '/api/clubs/1/courts/').single.body,
        {'name': 'Centre court', 'description': '', 'slot_minutes': 60, 'sports': [1], 'is_active': true});

    await tapLabel(tester, 'Saturday'); // Monday to Friday are chosen already
    await enter(tester, '0.00', '20');
    await tapText(tester, 'Add price window');
    final posted = api.calls('POST', '/api/courts/5/rates/').map((s) => s.body as Map).toList();
    expect([for (final r in posted) r['weekday']], [0, 1, 2, 3, 4, 5]);
    expect(posted.first, {'start_time': '08:00', 'end_time': '22:00', 'price': '20', 'weekday': 0});
    expect(find.text('Saturday'), findsWidgets);

    await tapLabel(tester, 'Back');
    await tapText(tester, 'Amenities and rentables');
    await enter(tester, 'Balls', 'Showers');
    await tapText(tester, 'Add item');
    await enter(tester, 'Balls', 'Rackets');
    await enter(tester, '1', '4');
    await enter(tester, 'Empty = amenity', '5');
    await tapText(tester, 'Add item');
    expect(api.calls('POST', '/api/clubs/1/equipment/').map((s) => s.body).toList(), [
      {'name': 'Showers', 'quantity': 1, 'court': null, 'rental_price': null},
      {'name': 'Rackets', 'quantity': 4, 'court': null, 'rental_price': '5'},
    ]);
    expect(find.text('Showers ×1'), findsOneWidget);
    expect(find.text('Rackets ×4'), findsOneWidget);
  });
}
