from __future__ import annotations

import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from hub_api.identity import IdentityError, OIDCVerifier


ISSUER = "https://identity.test/tenant"
AUDIENCE = "workbuddy-hub"


@pytest.fixture()
def oidc_provider():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tenant/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"},
            )
        if request.url.path == "/tenant/jwks":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = OIDCVerifier(
        ISSUER,
        AUDIENCE,
        client=client,
        cache_seconds=300,
        clock_skew_seconds=0,
    )

    def token(**overrides) -> str:
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-123",
            "exp": int(time.time()) + 300,
            "groups": ["employees", "department:design"],
            "departments": ["delivery"],
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})

    yield verifier, token, private_key
    verifier.close()


def test_oidc_verifier_uses_subject_and_maps_department_claims(oidc_provider):
    verifier, token, _ = oidc_provider
    identity = verifier.verify(token())
    assert identity.subject == "user-123"
    assert identity.auth_mode == "oidc"
    assert identity.groups == frozenset({"employees", "department:design"})
    assert identity.departments == frozenset({"delivery", "design"})


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other-issuer.test"},
        {"aud": "other-audience"},
        {"exp": 1},
        {"sub": ""},
        {"sub": 123},
    ],
)
def test_oidc_verifier_rejects_invalid_registered_claims(oidc_provider, claims):
    verifier, token, _ = oidc_provider
    with pytest.raises(IdentityError, match="oidc_token_invalid|oidc_subject_invalid"):
        verifier.verify(token(**claims))


def test_oidc_verifier_rejects_unknown_key_and_non_rs256(oidc_provider):
    verifier, token, private_key = oidc_provider
    unknown_key = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-123",
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "unknown-key"},
    )
    with pytest.raises(IdentityError, match="oidc_signing_key_not_found"):
        verifier.verify(unknown_key)

    hs256 = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-123",
            "exp": int(time.time()) + 300,
        },
        "not-a-public-key-but-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": "key-1"},
    )
    with pytest.raises(IdentityError, match="oidc_token_algorithm_rejected"):
        verifier.verify(hs256)


def test_oidc_verifier_rejects_cross_host_jwks():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"issuer": ISSUER, "jwks_uri": "https://attacker.test/jwks"},
        )

    verifier = OIDCVerifier(
        ISSUER,
        AUDIENCE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(IdentityError, match="oidc_jwks_host_mismatch"):
        verifier._refresh_keys()
    verifier.close()
