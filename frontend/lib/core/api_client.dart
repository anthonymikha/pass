// The only place that talks HTTP. Token auth: `Authorization: Token <token>`, the token kept in the browser's
// local storage (token_store.dart). A 401 means the token is dead: the app signs out and shows the login screen.
// The app is served from the same origin as the API (FE-13), so paths are enough.
import 'dart:async' show Zone, runZoned;
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'token_store.dart';

class ApiException implements Exception {
  ApiException(this.status, this.message, [this.body]);

  /// HTTP status; 0 for network errors.
  final int status;
  final String message;
  final Object? body;

  /// GEN-2: the stable error code of a business-rule refusal (`slot_taken`), if any.
  String? get code => body is Map ? (body as Map)['code'] as String? : null;

  bool get isUnauthorized => status == 401;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({String? baseUrl, http.Client? client})
      : baseUrl = baseUrl ?? const String.fromEnvironment('API_BASE_URL'),
        _http = client ?? http.Client();

  /// Shared instance used by the app. Tests replace it with `ApiClient(client: MockClient(...))`.
  static ApiClient instance = ApiClient();

  /// Empty = same origin as the page (web).
  final String baseUrl;
  final http.Client _http;

  String? get token => readToken();
  set token(String? value) => writeToken(value);

  /// GET responses kept in memory for [cacheTtl], so going back to a screen shows it at once without
  /// asking the server again. Stored as raw text and decoded per use (callers may mutate what they get).
  /// Any write (POST/PATCH/PUT/DELETE) clears it, so your own changes always show.
  /// ponytail: whole-cache clear on writes; per-path invalidation only if that ever matters.
  static const cacheTtl = Duration(seconds: 30);
  final _cache = <String, (DateTime, String)>{};

  /// Counts writes; screens kept alive in a tab compare it to know whether to refresh when shown again.
  int writes = 0;

  /// Runs [body] with every GET going to the server (pull-to-refresh, reload after a change).
  static Future<T> fresh<T>(Future<T> Function() body) => runZoned(body, zoneValues: {#apiFresh: true});

  /// Called when the server says the token is dead (401).
  void Function()? onUnauthorized;

  /// A query value may be a list: `{'sport': ['1', '2']}` sends `sport=1&sport=2`.
  Uri uri(String path, [Map<String, Object>? query]) {
    final base = baseUrl.isEmpty ? Uri.base : Uri.parse(baseUrl);
    final resolved = base.resolve(path);
    return query == null || query.isEmpty ? resolved : resolved.replace(queryParameters: query);
  }

  /// [fresh] skips the cache (also skipped inside [ApiClient.fresh]).
  Future<dynamic> get(String path, {Map<String, Object>? query, bool fresh = false}) async {
    final u = uri(path, query);
    final key = u.toString();
    final hit = _cache[key];
    if (!fresh && Zone.current[#apiFresh] != true && hit != null && DateTime.now().difference(hit.$1) < cacheTtl) {
      return _decode(hit.$2);
    }
    return _send(() => _http.get(u, headers: _headers(false)), cacheKey: key);
  }

  /// Every page of a paginated list (GEN-12), as one list.
  Future<List<dynamic>> getAll(String path, {Map<String, Object>? query}) async {
    final out = <dynamic>[];
    for (var page = 1;; page++) {
      final data = await get(path, query: {...?query, 'page': '$page'}) as Map<String, dynamic>;
      out.addAll(data['results'] as List<dynamic>);
      if (data['next'] == null) return out;
    }
  }

  Future<dynamic> post(String path, {Object? body}) => _unsafe((h) => _http.post(uri(path), headers: h, body: _encode(body)));

  Future<dynamic> patch(String path, {Object? body}) => _unsafe((h) => _http.patch(uri(path), headers: h, body: _encode(body)));

  Future<dynamic> put(String path, {Object? body}) => _unsafe((h) => _http.put(uri(path), headers: h, body: _encode(body)));

  Future<dynamic> delete(String path, {Object? body}) =>
      _unsafe((h) => _http.delete(uri(path), headers: h, body: _encode(body)));

  Future<dynamic> _unsafe(Future<http.Response> Function(Map<String, String> headers) call) {
    _cache.clear();
    writes++;
    return _send(() => call(_headers(true)));
  }

  /// Drops every cached GET (sign-in and sign-out).
  void clearCache() => _cache.clear();

  Map<String, String> _headers(bool unsafe) => {
        'Accept': 'application/json',
        if (unsafe) 'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Token $token',
      };

  String? _encode(Object? body) => body == null ? null : jsonEncode(body);

  static Object? _decode(String text) {
    if (text.isEmpty) return null;
    try {
      return jsonDecode(text);
    } catch (_) {
      return text;
    }
  }

  Future<dynamic> _send(Future<http.Response> Function() call, {String? cacheKey}) async {
    http.Response res;
    try {
      res = await call();
    } catch (e) {
      throw ApiException(0, 'Can’t reach PASS. Check your connection and try again.');
    }
    final text = utf8.decode(res.bodyBytes);
    final data = _decode(text);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      if (cacheKey != null) _cache[cacheKey] = (DateTime.now(), text);
      return data;
    }
    final err = ApiException(res.statusCode, _message(res.statusCode, data), data);
    if (err.isUnauthorized && token != null) onUnauthorized?.call();
    throw err;
  }

  static String _message(int status, Object? data) {
    if (status == 401) return 'You were signed out. Sign in again.';
    if (status == 404) return 'Not found. It may have been removed.';
    if (status == 429) return 'Too many attempts. Try again in a minute.';
    if (data is Map) {
      if (data['detail'] != null) return '${data['detail']}';
      for (final entry in data.entries) {
        final v = entry.value;
        final text = v is List && v.isNotEmpty ? (v.first is Map ? _message(status, v.first) : '${v.first}') : '$v';
        // DRF field errors: say which field ("password: This password is too common.").
        return entry.key == 'non_field_errors' ? text : '${entry.key.replaceAll('_', ' ')}: $text';
      }
    }
    if (status >= 500) return 'Something went wrong on our side. Try again.';
    return 'Request failed ($status).';
  }
}
