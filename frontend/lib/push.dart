import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'api.dart';

// FE-8: Firebase settings come from --dart-define; without them the app runs without pushes.
const _apiKey = String.fromEnvironment('FIREBASE_API_KEY');
const _senderId = String.fromEnvironment('FIREBASE_SENDER_ID');
const _projectId = String.fromEnvironment('FIREBASE_PROJECT_ID');
const _androidAppId = String.fromEnvironment('FIREBASE_ANDROID_APP_ID');
const _iosAppId = String.fromEnvironment('FIREBASE_IOS_APP_ID');

/// Phones only (FE-8): register this phone's token (NOTE-2) and open the session a push is about (NOTE-14).
Future<void> setupPush(GoRouter router, GlobalKey<ScaffoldMessengerState> messenger) async {
  final ios = defaultTargetPlatform == TargetPlatform.iOS;
  if (kIsWeb || _apiKey.isEmpty || !Api.instance.signedIn) return;
  try {
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp(
        options: FirebaseOptions(
          apiKey: _apiKey,
          appId: ios ? _iosAppId : _androidAppId,
          messagingSenderId: _senderId,
          projectId: _projectId,
          iosBundleId: 'app.pass.mobile',
        ),
      );
      void open(RemoteMessage m) {
        final id = m.data['id'];
        if (id != null && '${m.data['type']}'.startsWith(RegExp('training|session'))) router.go('/sessions/$id');
      }

      FirebaseMessaging.onMessageOpenedApp.listen(open);
      FirebaseMessaging.onMessage.listen((m) => messenger.currentState
          ?.showSnackBar(SnackBar(content: Text(m.notification?.title ?? 'Update'), action: SnackBarAction(label: 'Open', onPressed: () => open(m)))));
      // ponytail: the backend sends to registration tokens (FCM HTTP v1, NOTE-10); move to register()/onRegistered
      // (installation ids) only once the backend sends to those.
      // ignore: deprecated_member_use
      FirebaseMessaging.instance.onTokenRefresh.listen(_register);
      final first = await FirebaseMessaging.instance.getInitialMessage();
      if (first != null) open(first);
    }
    await FirebaseMessaging.instance.requestPermission();
    // ignore: deprecated_member_use
    final token = await FirebaseMessaging.instance.getToken();
    if (token != null) await _register(token);
  } catch (e) {
    debugPrint('Push is off: $e'); // a failed push setup never blocks the app (NOTE-13 in spirit)
  }
}

Future<void> _register(String token) async {
  if (!Api.instance.signedIn) return;
  Api.instance.deviceToken = token;
  await Api.instance.post('devices/', {'token': token, 'platform': defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android'});
}
