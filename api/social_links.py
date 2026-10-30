"""Redes sociales del perfil (Profile.social_links).

Se guarda lo que la persona escribe (usuario, @usuario, enlace o número) por red;
la app arma el enlace al abrirlo. Una red vacía se quita.
"""
from rest_framework import serializers

SOCIAL_NETWORKS = ("instagram", "tiktok", "youtube", "x", "facebook", "linkedin", "website", "whatsapp")
MAX_LINK_LENGTH = 200


def clean_social_links(value):
    """{red: texto} -> solo redes conocidas, sin espacios de sobra ni vacías."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise serializers.ValidationError({"social_links": "Debe ser un objeto {red: usuario o enlace}."})
    cleaned = {}
    for network, raw in value.items():
        if network not in SOCIAL_NETWORKS:
            raise serializers.ValidationError({"social_links": f"Red desconocida: {network}."})
        text = " ".join(str(raw or "").split())
        if len(text) > MAX_LINK_LENGTH:
            raise serializers.ValidationError({"social_links": f"{network}: máximo {MAX_LINK_LENGTH} caracteres."})
        if text:
            cleaned[network] = text
    return cleaned
