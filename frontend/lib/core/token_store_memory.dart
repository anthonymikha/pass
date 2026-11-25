// Test and non-web stand-in for token_store_web.dart.
String? _token;

String? readToken() => _token;

void writeToken(String? token) => _token = token;

/// The device's IANA time zone; unknown off the web.
String? deviceTimeZone() => null;
