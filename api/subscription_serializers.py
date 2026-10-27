from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Subscription
from .subscriptions import MAX_AMOUNT_CENTS, MIN_AMOUNT_CENTS

User = get_user_model()

_CURRENCY_LABELS = dict(Subscription.CURRENCY_CHOICES)


def _money(cents, currency):
    return f"${Decimal(cents) / 100:,.2f} {_CURRENCY_LABELS[currency]}"


class SubscriptionUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username"]


class SubscriptionSerializer(serializers.ModelSerializer):
    subscriber = SubscriptionUserSerializer(read_only=True)
    recipient = SubscriptionUserSerializer(read_only=True)
    amount = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)
    is_gift = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id", "subscriber", "recipient", "amount", "amount_cents", "currency",
            "auto_renew", "status", "is_active", "is_gift", "current_period_end", "created_at",
        ]
        read_only_fields = fields

    def get_amount(self, obj):
        return f"{Decimal(obj.amount_cents) / 100:.2f}"

    def get_is_gift(self, obj):
        return obj.subscriber_id != obj.recipient_id


class CheckoutRequestSerializer(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.ChoiceField(choices=list(_CURRENCY_LABELS))
    auto_renew = serializers.BooleanField(default=True)
    recipient_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        currency = attrs["currency"]
        try:
            amount = Decimal(str(attrs["amount"]).strip().replace(",", "."))
        except InvalidOperation:
            raise serializers.ValidationError({"amount": "Escribe un monto válido."})
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            raise serializers.ValidationError({"amount": "El monto admite hasta 2 decimales."})

        cents = int(amount * 100)
        if cents < MIN_AMOUNT_CENTS[currency]:
            raise serializers.ValidationError(
                {"amount": f"El mínimo es {_money(MIN_AMOUNT_CENTS[currency], currency)} al mes."}
            )
        if cents > MAX_AMOUNT_CENTS[currency]:
            raise serializers.ValidationError(
                {"amount": f"El máximo es {_money(MAX_AMOUNT_CENTS[currency], currency)} al mes."}
            )
        attrs["amount_cents"] = cents
        return attrs
