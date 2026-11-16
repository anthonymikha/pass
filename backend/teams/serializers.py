from rest_framework import serializers

from accounts.models import User
from accounts.serializers import CONNECTABLE_USERS, PersonSerializer
from config.api import VisibleRelatedField
from venues.models import Sport

from . import services
from .models import Group, GroupMember


class GroupSerializer(serializers.ModelSerializer):
    """TEAM-21: what anyone may read about a group. The view annotates `member_count` (active rows)."""

    owner = PersonSerializer(read_only=True)
    coach = PersonSerializer(read_only=True)
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = ["id", "name", "type", "sport", "owner", "coach", "member_count"]


class GroupCreateSerializer(serializers.ModelSerializer):
    """TEAM-20."""

    sport = VisibleRelatedField(queryset=Sport.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Group
        fields = ["name", "type", "sport"]


class GroupRenameSerializer(GroupCreateSerializer):
    """TEAM-30: the type never changes."""

    class Meta(GroupCreateSerializer.Meta):
        fields = ["name", "sport"]


class MemberSerializer(serializers.ModelSerializer):
    user = PersonSerializer(read_only=True)

    class Meta:
        model = GroupMember
        fields = ["id", "user", "status", "created_at"]


class InviteSerializer(serializers.Serializer):
    user = VisibleRelatedField(queryset=CONNECTABLE_USERS)  # TEAM-22: active, non-shadow


class ShadowPlayerAddSerializer(serializers.Serializer):
    # Any shadow player id passes here so another coach's gets TEAM-27's not_your_player, not "Not found.".
    player = VisibleRelatedField(queryset=User.objects.filter(email__isnull=True))


class CoachSerializer(serializers.Serializer):
    coach = VisibleRelatedField(queryset=CONNECTABLE_USERS)  # TEAM-29; a non-coach is not_a_coach in the service


class UserSearchSerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2)  # ACC-20


class CoachSearchSerializer(serializers.Serializer):
    q = serializers.CharField(required=False)
    club = serializers.IntegerField(required=False)


class PublicProfileSerializer(serializers.ModelSerializer):
    """ACC-21. Never email, phone or body data."""

    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "avatar", "is_coach", "coach_bio", "coach_rate", "coach_currency"]

    def get_avatar(self, user):
        return ""  # ponytail: signed avatar links (REC-30) arrive with storage; always empty until then

    def to_representation(self, user):
        data = super().to_representation(user)
        if not user.is_coach:  # the coach fields exist only for coaches
            for field in ("coach_bio", "coach_rate", "coach_currency"):
                del data[field]
        else:
            data["clubs"] = [{"id": c.id, "name": c.name} for c in services.affiliated_clubs(user)]
        return data
