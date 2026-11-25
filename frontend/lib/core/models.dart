// Shared model: the signed-in user (GET/PATCH /api/me/). Feature data stays as decoded JSON in the screens.
class Me {
  Me(this.json);

  final Map<String, dynamic> json;

  int get id => json['id'] as int;
  String get email => json['email'] as String? ?? '';
  String get fullName => json['full_name'] as String? ?? '';
  String get phone => json['phone'] as String? ?? '';
  String get timezone => json['timezone'] as String? ?? 'UTC';
  bool get isCoach => json['is_coach'] == true;
  String get coachBio => json['coach_bio'] as String? ?? '';
  String? get coachRate => json['coach_rate'] as String?;

  String get initials {
    final parts = fullName.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
    if (parts.isEmpty) return '?';
    return (parts.first[0] + (parts.length > 1 ? parts.last[0] : '')).toUpperCase();
  }
}
