from rest_framework.throttling import UserRateThrottle


class ClassMessageThrottle(UserRateThrottle):
    """Messages to a whole class, per sender (CLASS_MESSAGE_RATE, default 30 an hour) (B-9)."""

    scope = "class_message"
