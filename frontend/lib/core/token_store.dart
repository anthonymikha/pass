// Where the login token lives: the browser's local storage on the web (FE-13), memory elsewhere (tests).
export 'token_store_memory.dart' if (dart.library.js_interop) 'token_store_web.dart';
