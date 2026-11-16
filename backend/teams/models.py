from django.conf import settings
from django.db import models

from venues.models import Sport


class Group(models.Model):
    class Type(models.TextChoices):
        PLAY_GROUP = "play_group"
        TEAM = "team"

    type = models.CharField(max_length=20, choices=Type.choices)
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_groups")
    # Who runs training. Starts as the owner for teams; change this to hand the team to another coach.
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="coached_groups"
    )
    sport = models.ForeignKey(Sport, null=True, blank=True, on_delete=models.SET_NULL, related_name="groups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "groups"

    def __str__(self):
        return self.name


class GroupMember(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited"
        REQUESTED = "requested"
        ACTIVE = "active"

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="group_memberships")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INVITED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "group_members"
        constraints = [models.UniqueConstraint(fields=["group", "user"], name="group_members_unique")]

    def __str__(self):
        return f"{self.user} in {self.group} ({self.status})"
