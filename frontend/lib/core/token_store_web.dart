// The only file that touches the browser: local storage for the token (FE-13) and the device's time zone name.
import 'dart:js_interop';

import 'package:web/web.dart' as web;

const _key = 'pass_token';

String? readToken() => web.window.localStorage.getItem(_key);

void writeToken(String? token) =>
    token == null ? web.window.localStorage.removeItem(_key) : web.window.localStorage.setItem(_key, token);

@JS('Intl.DateTimeFormat')
external _DateTimeFormat _dateTimeFormat();

extension type _DateTimeFormat(JSObject _) implements JSObject {
  external _Options resolvedOptions();
}

extension type _Options(JSObject _) implements JSObject {
  external String? get timeZone;
}

/// The device's IANA time zone ("Asia/Beirut"), used as the default for a new club.
String? deviceTimeZone() {
  try {
    return _dateTimeFormat().resolvedOptions().timeZone;
  } catch (_) {
    return null;
  }
}
