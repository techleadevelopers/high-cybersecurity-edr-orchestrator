import asyncio
import textwrap

import pytest
from fakeredis import aioredis as fakeredis

from app.core.config import Settings


RSA_PRIVATE = textwrap.dedent(
    """
    -----BEGIN PRIVATE KEY-----
    MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQC13i7lZwY+0zYU
    G94CtqSaXoXyMqufGjS4HHvdb4arxuP2tTStEy8YRrNwbmUQw9t02V1fJrBn8eQi
    7VvC5bc0YfEyYkQEACq0bULefG/kQ5QikUauMf2snJou7lOVXgYF+PqYt7elZeFJ
    PqyA6Ozgq8VzoX1wJ/MxxlxuT0P+OYCS+QkFXbdo0gAqHKRUVOPQ7N0Qk+NxvQkz
    H6RgL/Vxq4sK3+jlL9i5gkTQ2VYxBJbU+qgjtL5FjfXq0Pv6fSuIkcYZQ7cV0Osg
    rnb/zLtPv2ez8YF7xUsSyio1fC59SFQAv48UAcwGjb71dbEpNQWqF2+RAgMBAAEC
    ggEAFnccrAJ/u05lt8G3BJPu5ZYBrhCB17WH8ZGL5rLhA7Jz3CGQRycC/SjqBxlE
    3fVYkDFGfJ0wUbeH64WGtse/HgL7gFtAAo6NVFs47Q5+g5I+73xEXJM9G8zbLzVQ
    qH0Vs0ksj6lskz0JxlXpya4lYgcGc5RePYrSbOWDiB2iQyge0frLYYX6rM4PeQR3
    k+WzJJdvHhuIzh1lkm0VYwjoOTNSquDFG7Zw0ypCkJY80JrNjSVA32+2PkMI+UwN
    QjN1pMSxj28uF5mQPXzkhF9fYPGSYPNbQuUrAn9IUIGi5sy8RCOafcohDJT7oqYG
    y4+Zi8EhHMTxPQKBgQDeFjeTQxiqRTMbDf1zT0D5tHOJrf0rbZWGAWJXQIcbO3aq
    beKU8ChbQA2J+EvY3DZUKdNEf/7L5VTCbrbwCZG9fQh1GfAXibVVtBNX74kJrA6+
    rlWCrRk1qoZJVwPl80HYevV7oN4FXU7Qq/XU/EfF++pK0kLk3RJUgfM1UwKBgQDA
    pv5dXeuKBTj+eqy/8zJbkWwx41hdvbxqLQyIhlUDfFz0Q/ndkUZ3DLQmpNdtJxTN
    KwpRjYjux5Yd2WuPnkqs/fTQQt4Q7fX+O7V8Gm/RliKjZDbdbS3gjpZkShIoLwIr
    ZHJMFjLv5G+clz7+KfYU76ul/Dnn34pDu3jNGMxwYwKBgC3Y6iN3Y3z4ib4pr5lF
    f3qG+Fc43H60QtiBJRAHpM3V7eQnWwV6/rNaV0nZX2yY+ZtFYz5AvByGiXWZ+zq+
    3UIANjmzLcn3XJETIl87u23s4MaXWDb9T1DqGnQ5+DrY48Fqs0hHSAx5Kd7PgMTc
    S6XZ05XIhE0v+ZIpAp8AkWZNW0soTfRfG5Fz2aNwG7G4lPCmSP+GNni6V0aVFNw/
    AVMDS7bBM6mGs1RMDGJv0aX8gQKB3Grxb1hQIQKBgCjVbX7QyA1e2DDeeofYwaf/
    DFcfu1Bz34rY7vWR8gN0bd6U+dAf2EFTp/g5mD8FkHy5eiooz+EVpImQP8UKPPW9
    4XSUSzOMMJ5vi5z/KVuAQMGTnD1RAbzIRJaW9raEfrzxbCoY15vXxL21aXfrIX6p
    A6Yyk1fPxn5xAoGALYWegph5PMe5lA6GS6lLr5j+3LqPoBMsByivEDUoCzVWrPSc
    ddmpFUpDKrFC3hJsNP63TfvW9pYW7sbVhpCXdDRu8wrikvkBZwU8aq1QJ9j1omZC
    VmA02SVsp8M01Zf/GNKLbhUcUMhGBK2gEMNmVPa0zMw9gkdHWRPWh/c=
    -----END PRIVATE KEY-----
    """
).strip()

RSA_PUBLIC = textwrap.dedent(
    """
    -----BEGIN PUBLIC KEY-----
    MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtd4u5WcGPtM2FBveAraak
    nhfIyq58aNLgce91vhqvG4/a1NK0TLxhGs3BuZREDG3TVl9XyawZ/HkIu1bwuW3N
    GHxMmJEBAAqtG1C3nxv5EOUIpFGrjH9rJyaLu5TlV4GBfj6mLe3pWXhST6sgOjs4
    KvFc6F9cCfzMcZcbk9D/jmAkvkJBV23aNIAKhykVFTj0OzdEJPjcb0JMx+kYC/1c
    auLCt/o5S/EuYJE0NlWMQSW1PqoI7S+RY316tD7+n0riJHGGUO3FdDrIK52/8y7T
    79ns/GBe8VLEsoqNXwufUhUAL+PFAHMBo2+9XWxKTUFqhdvkQIDAQAB
    -----END PUBLIC KEY-----
    """
).strip()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        billing_webhook_secret="test-webhook",
        jwt_private_key=RSA_PRIVATE,
        jwt_public_key=RSA_PUBLIC,
        jwt_active_kid="test-kid",
        jwt_algorithm="RS256",
        jwt_issuer="https://issuer.test",
        jwt_audience="blockremote-api",
        jwt_clock_skew_seconds=30,
        refresh_fingerprint_secret="fp-secret",
        refresh_base_ttl_minutes=60 * 24 * 7,
        refresh_max_ttl_minutes=60 * 24 * 14,
        refresh_extend_minutes=60 * 24,
    )


@pytest.fixture()
async def redis():
    client = await fakeredis.create_redis_pool()
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()
