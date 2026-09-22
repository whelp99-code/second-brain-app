"""Typed Phone History failures safe to map onto HTTP responses."""

from __future__ import annotations


class PhoneHistoryError(Exception):
    """Base class for expected product errors."""

    code = "PHONE_HISTORY_ERROR"
    status = 500


class ConfigurationError(PhoneHistoryError):
    code = "CONFIGURATION_ERROR"
    status = 500


class ValidationError(PhoneHistoryError):
    code = "INVALID_ARGUMENT"
    status = 400


class AuthenticationError(PhoneHistoryError):
    code = "UNAUTHORIZED"
    status = 401


class ConflictError(PhoneHistoryError):
    code = "CONFLICT"
    status = 409


class NotFoundError(PhoneHistoryError):
    code = "NOT_FOUND"
    status = 404


class RequestTooLargeError(PhoneHistoryError):
    code = "REQUEST_TOO_LARGE"
    status = 413


class StorageError(PhoneHistoryError):
    code = "STORAGE_ERROR"
    status = 500


class CryptoError(PhoneHistoryError):
    code = "CRYPTO_ERROR"
    status = 500
