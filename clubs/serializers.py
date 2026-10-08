from rest_framework import serializers

from .models import Club, Fixture
from .services import can_manage, leader_names


class ClubSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    leaders = serializers.SerializerMethodField()
    leader_ids = serializers.SerializerMethodField()
    member_count = serializers.IntegerField(read_only=True, default=0)
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Club
        fields = ["id", "name", "kind", "kind_label", "description", "meets", "location", "leaders", "leader_ids",
                  "is_active", "member_count", "can_manage"]
        extra_kwargs = {"description": {"max_length": 2000}}

    def get_leaders(self, obj):
        return leader_names(obj)

    def get_leader_ids(self, obj):
        return [u.pk for u in obj.leaders.all()]

    def get_can_manage(self, obj):
        request = self.context.get("request")
        return bool(request and can_manage(request.user, obj))

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the club a name.")
        school = self.context["request"].user.profile.school
        clash = Club.objects.filter(school=school, name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("There is already a club with this name.")
        return value


class FixtureSerializer(serializers.ModelSerializer):
    club_name = serializers.CharField(source="club.name", read_only=True)
    venue_label = serializers.CharField(source="get_venue_display", read_only=True)
    outcome = serializers.CharField(read_only=True)
    can_manage = serializers.SerializerMethodField()
    players = serializers.SerializerMethodField()

    class Meta:
        model = Fixture
        fields = ["id", "club", "club_name", "date", "start_time", "opponent", "venue", "venue_label", "location",
                  "competition", "team", "our_score", "their_score", "result_note", "outcome", "report", "players",
                  "can_manage"]
        read_only_fields = ["club"]
        extra_kwargs = {"report": {"max_length": 4000}}

    def get_can_manage(self, obj):
        request = self.context.get("request")
        return bool(request and can_manage(request.user, obj.club))

    def get_players(self, obj):
        """The squad: everyone for the club's staff; for other staff, only students they can see."""
        visible = self.context.get("visible_ids")
        manage = self.get_can_manage(obj)
        return [{"id": s.id, "name": f"{s.first_name} {s.last_name}"} for s in obj.players.all()
                if manage or visible is None or s.id in visible]

    def validate_opponent(self, value):
        if not value.strip():
            raise serializers.ValidationError("Say who they are playing, or the event.")
        return value.strip()

    def validate(self, attrs):
        ours = attrs.get("our_score", getattr(self.instance, "our_score", None))
        theirs = attrs.get("their_score", getattr(self.instance, "their_score", None))
        if (ours is None) != (theirs is None):
            raise serializers.ValidationError({"our_score": ["Give both scores, or neither."]})
        return attrs
