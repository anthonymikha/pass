import 'package:flutter/widgets.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:go_router/go_router.dart';

import 'app.dart';
import 'core/app_state.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  usePathUrlStrategy(); // path-based URLs; Django returns index.html for app paths (FE-13)
  GoRouter.optionURLReflectsImperativeAPIs = true; // a pushed screen's path is in the address bar, so refresh keeps it
  await AppState.instance.bootstrap();
  runApp(const PassApp());
}
