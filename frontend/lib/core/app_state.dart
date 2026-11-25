// App-wide session state: the signed-in user, the clubs where they are on the club side, and the coach badge.
import 'package:flutter/widgets.dart';

import 'api_client.dart';
import 'models.dart';

class AppState extends ChangeNotifier {
  AppState();

  static final AppState instance = AppState();

  /// Test hook: set the signed-in user (and their club-side clubs) without a network call.
  @visibleForTesting
  void setMeForTest(Map<String, dynamic>? value, {List<Map<String, dynamic>> clubs = const []}) {
    me = value == null ? null : Me(value);
    clubSide = clubs;
    ready = true;
    notifyListeners();
  }

  /// Read live so tests can swap `ApiClient.instance`.
  ApiClient get api => ApiClient.instance..onUnauthorized = _signedOut;
  Me? me;
  bool ready = false; // first /api/me/ check done

  /// Clubs the user owns or is club staff of (FE-11), from GET /api/me/clubs/; the Club tab shows when not empty.
  List<Map<String, dynamic>> clubSide = const [];

  /// FE-8: training requests waiting for this coach's answer.
  int requestCount = 0;

  bool get signedIn => me != null;

  /// Called once at startup: a stored token signs the user straight in.
  Future<void> bootstrap() async {
    if (api.token != null) {
      try {
        me = Me(await api.get('/api/me/') as Map<String, dynamic>);
      } on ApiException {
        me = null;
      }
    }
    ready = true;
    await _afterAuthChange();
  }

  Future<void> login(String email, String password) async {
    final data = await api.post('/api/auth/login/', body: {'email': email, 'password': password});
    await _signedIn(data as Map<String, dynamic>);
  }

  Future<void> register(String fullName, String email, String password) async {
    final data =
        await api.post('/api/auth/register/', body: {'full_name': fullName, 'email': email, 'password': password});
    await _signedIn(data as Map<String, dynamic>);
  }

  Future<void> _signedIn(Map<String, dynamic> data) async {
    api.token = data['token'] as String;
    api.clearCache();
    me = Me(data['user'] as Map<String, dynamic>);
    await _afterAuthChange();
  }

  /// PATCH /api/me/ with any profile fields; updates [me].
  Future<void> updateMe(Map<String, Object?> fields) async {
    me = Me(await api.patch('/api/me/', body: fields) as Map<String, dynamic>);
    await refresh();
  }

  /// ACC-31: logout keeps the token on the server; the app forgets it.
  Future<void> logout() async {
    try {
      await api.post('/api/auth/logout/');
    } on ApiException {
      // Already signed out on the server; continue locally.
    }
    _signedOut();
  }

  /// ACC-33. Throws on a wrong password or `owns_club`.
  Future<void> deleteAccount(String password) async {
    await api.delete('/api/me/', body: {'password': password});
    _signedOut();
  }

  /// Re-reads the club-side clubs and the coach badge (app open, a tab shown again, after a change).
  Future<void> refresh() async {
    if (!signedIn) return;
    try {
      final clubs = await api.getAll('/api/me/clubs/');
      clubSide = [
        for (final c in clubs.cast<Map<String, dynamic>>())
          if ((c['roles'] as List).any((r) => r == 'owner' || r == 'staff')) c,
      ];
      var count = 0;
      if (me!.isCoach) {
        final waiting = await ApiClient.fresh(() => api.getAll('/api/me/sessions/', query: {'status': 'requested'}));
        count = waiting.where((s) => (s['coach'] as Map?)?['id'] == me!.id).length;
      }
      requestCount = count;
    } on ApiException {
      // Ignore: the tab and the badge are hints only; the next refresh tries again.
    }
    notifyListeners();
  }

  /// The club-side roles of the user in [clubId] (`owner`, `staff`).
  bool isOwner(int clubId) =>
      clubSide.any((c) => c['id'] == clubId && (c['roles'] as List).contains('owner'));

  void _signedOut() {
    api.token = null;
    api.clearCache();
    me = null;
    clubSide = const [];
    requestCount = 0;
    notifyListeners();
  }

  Future<void> _afterAuthChange() async {
    notifyListeners();
    await refresh();
  }
}
