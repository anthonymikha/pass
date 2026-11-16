from django.db import transaction
from django.db.models import Q
from rest_framework import generics, mixins, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config.api import BusinessError

from . import services
from .models import ClubCurrency, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, PriceOverride
from .serializers import (
    ClosureSerializer, ClubCurrencySerializer, ClubCurrencyUpdateSerializer, ClubSearchSerializer, ClubSerializer, MyClubSerializer,
    CourtSerializer, EquipmentSerializer, MemberCreateSerializer, MemberSerializer, MemberUpdateSerializer,
    OfferSerializer, OverridePriceSerializer, OverrideSerializer, RateSerializer, SearchParamsSerializer, court_detail,
)

SAFE = permissions.SAFE_METHODS


def seen_club(user, pk):
    """GEN-3: a club the caller cannot see does not exist for them."""
    return get_object_or_404(services.visible_clubs(user), pk=pk)


def public_reads(view):
    """ACC-3: GET needs no sign-in; everything else does."""
    return [permissions.AllowAny() if view.request.method in SAFE else permissions.IsAuthenticated()]


class ConfigAccess:
    """Visibility before permission (GEN-3), then owner only (ACC-5, ACC-6: staff change no configuration)."""

    owner_read = True  # reads of configuration are the owner's too; False where other signed-in users may read

    def authorize(self, club, court=None):
        owner = club.owner_id == self.request.user.id
        if court is not None and not court.is_active and not owner:
            raise NotFound()  # CLUB-31: an inactive court is invisible to others
        if not owner and (self.owner_read or self.request.method not in SAFE):
            raise PermissionDenied()
        self.club, self.court = club, court

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "club": getattr(self, "club", None)}


class ConfigList(ConfigAccess, generics.ListCreateAPIView):
    """Rows under the club (or court) named in the URL."""

    parent = "club"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.parent == "court":
            court = get_object_or_404(Court.objects.select_related("club"), pk=kwargs["court"])
            self.authorize(seen_club(request.user, court.club_id), court)
        else:
            self.authorize(seen_club(request.user, kwargs["club"]))


class ConfigDetail(ConfigAccess, generics.RetrieveUpdateDestroyAPIView):
    http_method_names = ["get", "patch", "delete", "head", "options"]  # no PUT, like /api/me/

    def parents(self, obj):
        """(club, court or None) the row belongs to."""
        return obj.club, None

    def get_object(self):
        obj = get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        club, court = self.parents(obj)
        self.authorize(seen_club(self.request.user, club.pk), court)
        return obj


# ---- clubs ----

class ClubListView(generics.ListCreateAPIView):
    """GET: public search (CLUB-30). POST: any user creates a club and owns it (CLUB-1)."""

    serializer_class = ClubSerializer

    def get_permissions(self):
        return public_reads(self)

    def list(self, request):
        params = SearchParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        page = self.paginate_queryset(services.search_clubs(**params.validated_data))
        return self.get_paginated_response(ClubSearchSerializer(page, many=True).data)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class MyClubsView(generics.ListAPIView):
    """CLUB-33: the clubs the caller owns or works at."""

    serializer_class = MyClubSerializer

    def get_queryset(self):
        return services.my_clubs(self.request.user)


class ClubView(generics.RetrieveUpdateAPIView):
    """CLUB-2, CLUB-3. Clubs are never deleted (CLUB-4)."""

    serializer_class = ClubSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        club = seen_club(self.request.user, self.kwargs["pk"])
        if self.request.method not in SAFE and club.owner_id != self.request.user.id:
            raise PermissionDenied()
        return club

    def perform_update(self, serializer):
        services.check_base_currency(serializer.instance, serializer.validated_data)
        serializer.save()


class CurrencyList(ConfigList):
    serializer_class = ClubCurrencySerializer

    def get_queryset(self):
        return self.club.currencies.order_by("id")

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.add_currency(self.club, data["currency"], data["exchange_rate"])  # CLUB-5


class CurrencyDetail(ConfigDetail):
    queryset = ClubCurrency.objects.select_related("club")

    def get_serializer_class(self):
        return ClubCurrencySerializer if self.request.method in SAFE else ClubCurrencyUpdateSerializer

    def perform_destroy(self, instance):
        services.remove_currency(instance)  # CLUB-7


# ---- courts ----

class CourtList(ConfigList):
    serializer_class = CourtSerializer
    owner_read = False

    def get_queryset(self):
        courts = self.club.courts.order_by("id")
        return courts if self.club.owner_id == self.request.user.id else courts.filter(is_active=True)

    def perform_create(self, serializer):
        serializer.save(club=self.club)  # CLUB-8


class CourtDetail(ConfigDetail):
    """GET: public court detail (CLUB-31). PATCH, DELETE: CLUB-9, CLUB-10."""

    queryset = Court.objects.select_related("club")
    serializer_class = CourtSerializer
    owner_read = False

    def get_permissions(self):
        return public_reads(self)

    def parents(self, court):
        return court.club, court

    def retrieve(self, request, *args, **kwargs):
        court = self.get_object()
        if not court.is_active:
            raise NotFound()  # CLUB-31, even for the owner
        return Response(court_detail(court))

    def perform_destroy(self, instance):
        services.delete_court(instance)


# ---- rates ----

class RateList(ConfigList):
    parent = "court"
    serializer_class = RateSerializer

    def get_queryset(self):
        return self.court.rates.order_by("weekday", "start_time", "id")

    def perform_create(self, serializer):
        with transaction.atomic():
            services.lock_court(self.court)
            services.check_rate_overlap(self.court, serializer.validated_data)  # CLUB-12
            serializer.save(court=self.court)


class RateDetail(ConfigDetail):
    queryset = CourtRate.objects.select_related("court__club")
    serializer_class = RateSerializer

    def parents(self, rate):
        return rate.court.club, rate.court

    def perform_update(self, serializer):
        with transaction.atomic():
            services.lock_court(serializer.instance.court)
            services.check_rate_overlap(serializer.instance.court, serializer.validated_data, serializer.instance)  # CLUB-12
            serializer.save()


# ---- closures ----

class ClosureContext:
    def get_serializer_context(self):
        # CLUB-16: the response to a create or a change lists the conflicts
        return {**super().get_serializer_context(), "conflicts": self.request.method in ("POST", "PATCH")}


class ClosureList(ClosureContext, ConfigList):
    parent = "court"
    serializer_class = ClosureSerializer

    def get_queryset(self):
        return self.court.blockouts.order_by("starts_on", "id")

    def perform_create(self, serializer):
        serializer.save(court=self.court)


class ClosureDetail(ClosureContext, ConfigDetail):
    queryset = CourtBlockout.objects.select_related("court__club")
    serializer_class = ClosureSerializer

    def parents(self, closure):
        return closure.court.club, closure.court


# ---- equipment ----

class EquipmentList(ConfigList):
    serializer_class = EquipmentSerializer

    def get_queryset(self):
        return self.club.equipment.order_by("id")

    def perform_create(self, serializer):
        serializer.save(club=self.club)


class EquipmentDetail(ConfigDetail):
    queryset = Equipment.objects.select_related("club")
    serializer_class = EquipmentSerializer

    def perform_destroy(self, instance):
        services.delete_equipment(instance)  # CLUB-19


# ---- overrides ----

class OverrideList(ConfigList):
    serializer_class = OverrideSerializer

    def get_queryset(self):
        return PriceOverride.objects.filter(Q(court_rate__court__club=self.club) | Q(equipment__club=self.club)).order_by("id")

    def perform_create(self, serializer):
        serializer.instance = services.add_override(self.club, serializer.validated_data)  # CLUB-20


class OverrideDetail(ConfigDetail):
    queryset = PriceOverride.objects.select_related("court_rate__court__club", "equipment__club")

    def get_serializer_class(self):
        return OverrideSerializer if self.request.method in SAFE else OverridePriceSerializer

    def parents(self, override):
        if override.court_rate_id:
            return override.court_rate.court.club, None
        return override.equipment.club, None


# ---- offers ----

class OfferList(ConfigList):
    """Owner: every offer of the club. Anyone else who sees the club: the offers shown to a player (CLUB-32)."""

    serializer_class = OfferSerializer
    owner_read = False

    def get_queryset(self):
        if self.club.owner_id == self.request.user.id:
            return self.club.discounts.order_by("id")
        court = self.request.query_params.get("court")
        if court is not None and not court.isdigit():
            raise ValidationError({"court": "A court id is a whole number."})
        return services.player_offers(self.club, self.request.user, court)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.create_offer(serializer, self.club)  # CLUB-22, CLUB-24
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class OfferDetail(ConfigDetail):
    queryset = Discount.objects.select_related("club")
    serializer_class = OfferSerializer


# ---- members ----

def member_row(request, pk, allow_self=False):
    """404 if the caller cannot see the row, 403 if they may not touch it (owner only, or the member themselves)."""
    member = get_object_or_404(ClubMember.objects.select_related("user"), pk=pk)
    club = seen_club(request.user, member.club_id)
    owner = club.owner_id == request.user.id
    mine = member.user_id == request.user.id
    if not (owner or mine or services.can_list_members(request.user, club)):
        raise NotFound()
    if not (owner or (allow_self and mine)):
        raise PermissionDenied()
    return member


class MemberList(generics.ListCreateAPIView):
    """GET: the owner and current members list (CLUB-29); others 404. POST: the owner adds staff or a player (CLUB-25)."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.club = seen_club(request.user, kwargs["club"])

    def get_serializer_class(self):
        return MemberCreateSerializer if self.request.method == "POST" else MemberSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "club": getattr(self, "club", None)}

    def get_queryset(self):
        rows = self.club.members.select_related("user").order_by("id")
        if self.club.owner_id == self.request.user.id:
            return rows
        if not services.can_list_members(self.request.user, self.club):
            raise NotFound()
        return services.current_members(self.club).select_related("user").order_by("id")  # ACC-2

    def create(self, request, *args, **kwargs):
        if self.club.owner_id != request.user.id:
            raise PermissionDenied()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["email"] is None:
            raise BusinessError("user_not_found", "No active user has this email.")
        member = services.add_member(self.club, data["email"], data["role"], data.get("expires_on"))
        return Response(MemberSerializer(member).data, status=status.HTTP_201_CREATED)


class MemberDetail(mixins.UpdateModelMixin, mixins.DestroyModelMixin, generics.GenericAPIView):
    """PATCH expires_on: owner (CLUB-29). DELETE: the owner removes, or the member leaves (CLUB-28)."""

    serializer_class = MemberUpdateSerializer
    http_method_names = ["patch", "delete", "options"]

    def get_object(self):
        return member_row(self.request, self.kwargs["pk"], allow_self=self.request.method == "DELETE")

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)


class MemberApproveView(generics.GenericAPIView):
    """CLUB-27: the owner approves a pending coach. Rejecting is DELETE on the row."""

    serializer_class = MemberSerializer

    def post(self, request, pk):
        member = member_row(request, pk)
        if member.status != ClubMember.Status.ACTIVE:  # GEN-5: approving an active row changes nothing
            member.status = ClubMember.Status.ACTIVE
            member.save(update_fields=["status"])
        return Response(MemberSerializer(member).data)


class CoachRequestView(generics.GenericAPIView):
    """CLUB-26: a coach asks to be affiliated with a club."""

    serializer_class = MemberSerializer

    def post(self, request, club):
        club = seen_club(request.user, club)
        if not request.user.is_coach:
            raise PermissionDenied()
        member = services.add_member(club, request.user, ClubMember.Role.COACH, status=ClubMember.Status.PENDING)
        return Response(MemberSerializer(member).data, status=status.HTTP_201_CREATED)
