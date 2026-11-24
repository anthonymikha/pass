import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// Backend address for phone builds (`--dart-define=API_URL=https://host`). Empty on the web: same origin.
const apiUrl = String.fromEnvironment('API_URL');

class ApiError implements Exception {
  ApiError(this.status, this.message, [this.code]);
  final int status;
  final String message;
  final String? code;

  @override
  String toString() => message;
}

/// The one REST client (FE spec, "Build"): token, signed-in user, JSON calls.
class Api extends ChangeNotifier {
  Api._();
  static final instance = Api._();

  final _storage = const FlutterSecureStorage();
  http.Client client = http.Client(); // replaced by a MockClient in tests
  String? token;
  Map<String, dynamic>? me;
  String? deviceToken; // FCM token of this phone, sent with logout (ACC-31)
  VoidCallback? onSignedIn;

  bool get signedIn => token != null && me != null;
  int get myId => me!['id'] as int;

  Future<void> load() async {
    tzdata.initializeTimeZones();
    try {
      token = await _storage.read(key: 'token');
    } catch (_) {
      token = null; // storage can be unavailable (private browsing): just ask to log in
    }
    if (token == null) return;
    try {
      me = await get('me/');
    } on ApiError catch (e) {
      if (e.status == 401) await _forget();
    } catch (_) {
      // offline: the screens will show the error and offer a retry
    }
  }

  Uri _uri(String path, Map<String, String?>? query) {
    final base = apiUrl.isNotEmpty ? Uri.parse(apiUrl) : Uri.base;
    final q = {for (final e in (query ?? {}).entries) if (e.value != null && e.value!.isNotEmpty) e.key: e.value!};
    return Uri(
      scheme: base.scheme,
      host: base.host,
      port: base.hasPort ? base.port : null,
      path: '/api/$path',
      queryParameters: q.isEmpty ? null : q,
    );
  }

  Future<dynamic> send(String method, String path, {Object? body, Map<String, String?>? query}) async {
    final req = http.Request(method, _uri(path, query));
    req.headers['Accept'] = 'application/json';
    if (token != null) req.headers['Authorization'] = 'Token $token';
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final http.Response res;
    try {
      res = await http.Response.fromStream(await client.send(req));
    } catch (_) {
      throw ApiError(0, 'Cannot reach the server. Check your connection.');
    }
    final data = res.bodyBytes.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    if (res.statusCode == 401 && token != null) {
      await _forget();
      throw ApiError(401, 'Please log in again.');
    }
    if (res.statusCode >= 400) {
      throw ApiError(res.statusCode, _message(data), data is Map ? data['code'] as String? : null);
    }
    return data;
  }

  Future<dynamic> get(String path, [Map<String, String?>? query]) => send('GET', path, query: query);
  Future<dynamic> post(String path, [Object? body]) => send('POST', path, body: body ?? {});
  Future<dynamic> patch(String path, Object body) => send('PATCH', path, body: body);
  Future<dynamic> delete(String path, [Object? body]) => send('DELETE', path, body: body);

  /// Rows of a list endpoint, paged (GEN-12) or not.
  // ponytail: first page only (50 rows); add "load more" when a list outgrows it.
  Future<List<Map<String, dynamic>>> rows(String path, [Map<String, String?>? query]) async {
    final data = await get(path, query);
    final list = data is Map ? data['results'] as List : data as List;
    return list.cast<Map<String, dynamic>>();
  }

  Future<void> login(String email, String password) =>
      _signIn('auth/login/', {'email': email, 'password': password});

  Future<void> register(String email, String password, String fullName) =>
      _signIn('auth/register/', {'email': email, 'password': password, 'full_name': fullName});

  Future<void> _signIn(String path, Map body) async {
    final data = await post(path, body);
    token = data['token'] as String;
    me = (data['user'] as Map).cast<String, dynamic>();
    try {
      await _storage.write(key: 'token', value: token);
    } catch (_) {}
    notifyListeners();
    onSignedIn?.call();
  }

  Future<void> refreshMe() async {
    me = await get('me/');
    notifyListeners();
  }

  Future<void> logout() async {
    try {
      await post('auth/logout/', {if (deviceToken != null) 'device_token': deviceToken});
    } catch (_) {}
    await _forget();
  }

  Future<void> deleteAccount(String password) async {
    await delete('me/', {'password': password});
    await _forget();
  }

  Future<void> _forget() async {
    token = null;
    me = null;
    try {
      await _storage.delete(key: 'token');
    } catch (_) {}
    notifyListeners();
  }
}

String _message(dynamic data) {
  if (data is Map && data['detail'] != null) return '${data['detail']}';
  String flat(dynamic d) {
    if (d is Map) {
      return d.entries
          .map((e) => e.key == 'non_field_errors' ? flat(e.value) : '${_label(e.key)}: ${flat(e.value)}')
          .join('\n');
    }
    if (d is List) return d.map(flat).where((s) => s.isNotEmpty).join(' ');
    return d == null ? 'Something went wrong.' : '$d';
  }

  return flat(data);
}

String _label(String field) => field.replaceAll('_', ' ');

// ---- formatting (money arrives as decimal strings, times as UTC instants) ----

String money(Object? amount, [String? currency]) =>
    amount == null ? '' : NumberFormat.simpleCurrency(name: currency ?? 'USD').format(num.parse('$amount'));

/// A UTC instant in the device's timezone.
String when(String iso) => DateFormat('EEE d MMM, HH:mm').format(DateTime.parse(iso).toLocal());

/// A UTC instant in a club's timezone (FE spec: court times in the club's timezone).
tz.TZDateTime inZone(String iso, String zone) => tz.TZDateTime.from(DateTime.parse(iso), tz.getLocation(zone));

String hm(DateTime d) => DateFormat.Hm().format(d);
String day(DateTime d) => DateFormat('EEE d MMM').format(d);
String isoDate(DateTime d) => DateFormat('yyyy-MM-dd').format(d);

/// "09:00:00" -> "09:00"; an end of "00:00" is midnight (GEN-11).
String clock(String t, {bool end = false}) => end && t.startsWith('00:00') ? '24:00' : t.substring(0, 5);

const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']; // 0 = Monday

List<String> timezones() => tz.timeZoneDatabase.locations.keys.toList()..sort();
