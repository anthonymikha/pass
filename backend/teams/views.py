from django.db.models import Count, OuterRef, Q, Subquery
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from accounts.models import User
from venues.services import visible_clubs

from . import services
from .models import Group, GroupMember
from .serializers import (
    CoachSearchSerializer, CoachSerializer, GroupCreateSerializer, GroupRenameSerializer, GroupSerializer,
    InviteSerializer, GroupMemberSerializer, MyGroupSerializer, MyGroupsQuerySerializer, PublicProfileSerializer, ShadowPlayerAddSerializer, UserSearchSerializer,
)


def groups():
    return Group.objects.select_related("created_by", "coach").annotate(
        member_count=Count("members", filter=Q(members__status=GroupMember.Status.ACTIVE)))


def member_response(row, created):
    return Response(GroupMemberSerializer(row).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class GroupBaseView(generics.GenericAPIView):
    """Every group is visible by id (TEAM-21); `manager_only` turns it into a 403 for others."""

    serializer_class = GroupSerializer
    manager_only = False

    def get_group(self, pk):
        group = get_object_or_404(groups(), pk=pk)
        if self.manager_only and not services.is_group_manager(self.request.user, group):
            raise PermissionDenied("Only a group manager can do this.")
        return group


class GroupCreateView(generics.GenericAPIView):
    serializer_class = GroupCreateSerializer

    @extend_schema(responses=GroupSerializer)
    def post(self, request):
        """TEAM-20."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = services.create_group(request.user, **serializer.validated_data)
        return Response(GroupSerializer(groups().get(pk=group.pk)).data, status=status.HTTP_201_CREATED)


class GroupDetailView(GroupBaseView):
    def get(self, request, pk):
        """TEAM-21: anyone."""
        return Response(self.get_serializer(self.get_group(pk)).data)

    @extend_schema(request=GroupRenameSerializer)
    def patch(self, request, pk):
        """TEAM-30: a group manager renames."""
        self.manager_only = True
        serializer = GroupRenameSerializer(self.get_group(pk), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self.get_serializer(self.get_group(pk)).data)

    def delete(self, request, pk):
        """TEAM-30: a group manager."""
        self.manager_only = True
        services.delete_group(self.get_group(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupMembersView(GroupBaseView):
    serializer_class = GroupMemberSerializer

    def get(self, request, pk):
        """TEAM-21: only active members and group managers; anyone else gets a 404 (GEN-3)."""
        group = self.get_group(pk)
        if not (services.is_group_manager(request.user, group) or services.is_active_member(request.user, group)):
            raise NotFound()
        rows = group.members.select_related("user").order_by("user__full_name", "id")
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(request=InviteSerializer)
    def post(self, request, pk):
        """TEAM-22: a group manager invites; 201 new, 200 otherwise."""
        self.manager_only = True
        group = self.get_group(pk)
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return member_response(*services.invite(group, request.user, serializer.validated_data["user"]))


class GroupMemberDetailView(GroupBaseView):
    serializer_class = GroupMemberSerializer

    def delete(self, request, pk, user_id):
        """TEAM-26, TEAM-23 decline: leave, decline, remove or reject. `user_id` is the member's user id."""
        services.remove_member(self.get_group(pk), request.user, user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupMemberAcceptView(GroupBaseView):
    serializer_class = GroupMemberSerializer
    manager_only = True

    @extend_schema(request=None)
    def post(self, request, pk, user_id):
        """TEAM-25: a group manager accepts a join request."""
        return Response(GroupMemberSerializer(services.accept_request(self.get_group(pk), user_id)).data)


class GroupAcceptView(GroupBaseView):
    serializer_class = GroupMemberSerializer

    @extend_schema(request=None)
    def post(self, request, pk):
        """TEAM-23: the invitee accepts."""
        return Response(GroupMemberSerializer(services.accept_invite(self.get_group(pk), request.user)).data)


class GroupJoinView(GroupBaseView):
    serializer_class = GroupMemberSerializer

    @extend_schema(request=None)
    def post(self, request, pk):
        """TEAM-24: 201 new request, 200 otherwise."""
        return member_response(*services.ask_to_join(self.get_group(pk), request.user))


class GroupShadowPlayersView(GroupBaseView):
    serializer_class = ShadowPlayerAddSerializer
    manager_only = True

    @extend_schema(responses=GroupMemberSerializer)
    def post(self, request, pk):
        """TEAM-27: 201 new, 200 if already a member."""
        group = self.get_group(pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return member_response(*services.add_shadow_player(group, request.user, serializer.validated_data["player"]))


class GroupCoachView(GroupBaseView):
    serializer_class = CoachSerializer
    manager_only = True  # TEAM-29: the team coach; for a play group the creator gets not_a_team

    @extend_schema(responses=GroupSerializer)
    def post(self, request, pk):
        """TEAM-29: hand the team over."""
        group = self.get_group(pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.hand_over(group, serializer.validated_data["coach"])
        return Response(GroupSerializer(groups().get(pk=pk)).data)  # the caller may no longer be a manager


class UserSearchView(generics.ListAPIView):
    """ACC-20."""

    serializer_class = PublicProfileSerializer

    def get_queryset(self):
        params = UserSearchSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        return services.search_users(self.request.user, params.validated_data["q"])


class CoachSearchView(generics.ListAPIView):
    """ACC-22. A club the caller cannot see gives an empty list."""

    serializer_class = PublicProfileSerializer

    def get_queryset(self):
        params = CoachSearchSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        data, club = params.validated_data, None
        if "club" in data:
            club = visible_clubs(self.request.user).filter(pk=data["club"]).first()
            if club is None:
                return User.objects.none()
        return services.search_coaches(self.request.user, data.get("q"), club)


class PublicProfileView(generics.RetrieveAPIView):
    """ACC-23: blocked pair, shadow or inactive users are a 404."""

    serializer_class = PublicProfileSerializer

    def get_queryset(self):
        return services.findable_users(self.request.user)


class MyGroupsView(generics.ListAPIView):
    """TEAM-32: groups where the caller has a member row, with their own status."""

    serializer_class = MyGroupSerializer

    def get_queryset(self):
        params = MyGroupsQuerySerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        mine = GroupMember.objects.filter(user=self.request.user)
        if "status" in params.validated_data:
            mine = mine.filter(status=params.validated_data["status"])
        own_status = GroupMember.objects.filter(group=OuterRef("pk"), user=self.request.user).values("status")
        return groups().filter(pk__in=mine.values("group")).annotate(my_status=Subquery(own_status)).order_by("name", "id")
