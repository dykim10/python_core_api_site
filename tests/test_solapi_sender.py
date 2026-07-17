from unittest.mock import patch

import pytest

from app.services import solapi_service as svc


@pytest.fixture(autouse=True)
def clear_pending_mfa():
    svc._pending_mfa.clear()
    yield
    svc._pending_mfa.clear()


def test_normalize_phone_strips_non_digits():
    assert svc._normalize_phone("010-1234-5678") == "01012345678"


def test_normalize_phone_rejects_invalid():
    assert svc._normalize_phone("123") is None


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_list_sender_numbers_active_only(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    mock_request.return_value = (
        200,
        {
            "senderIds": [
                {"phoneNumber": "01011112222", "status": "ACTIVE"},
                {"phoneNumber": "01033334444", "status": "PENDING"},
            ]
        },
    )

    result = svc.list_sender_numbers(include_all_statuses=False)

    assert result == {"senders": ["01011112222"]}


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_list_sender_numbers_all_statuses(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    mock_request.return_value = (
        200,
        {
            "senderIds": [
                {"phoneNumber": "01011112222", "status": "ACTIVE"},
                {"phoneNumber": "01033334444", "status": "PENDING"},
            ]
        },
    )

    result = svc.list_sender_numbers(include_all_statuses=True)

    assert result["senders"] == [
        {"phoneNumber": "01011112222", "status": "ACTIVE"},
        {"phoneNumber": "01033334444", "status": "PENDING"},
    ]


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_register_sender_success(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    mock_request.side_effect = [
        (201, {"senderIds": [{"phoneNumber": "01012345678", "status": "PENDING"}]}),
        (200, {"mfa": {"transactionId": "tx-abc"}}),
    ]

    result = svc.register_sender("010-1234-5678")

    assert result == {"ok": True, "phone_number": "01012345678"}
    assert svc._pending_mfa["01012345678"][0] == "tx-abc"


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_register_sender_auth_failure(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    mock_request.side_effect = [
        (201, {"senderIds": []}),
        (400, {"errorMessage": "이미 등록된 번호입니다."}),
    ]

    result = svc.register_sender("01012345678")

    assert result == {"error": "이미 등록된 번호입니다."}


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_register_sender_uses_ars_auth_type(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    mock_request.side_effect = [
        (201, {"senderIds": [{"phoneNumber": "01012345678", "status": "PENDING"}]}),
        (200, {"mfa": {"transactionId": "tx-abc"}}),
    ]

    svc.register_sender("01012345678")

    auth_call = mock_request.call_args_list[1]
    mfa_header = auth_call.kwargs["extra_headers"]["x-mfa-data"]
    assert '"authType": "ARS"' in mfa_header or '"authType":"ARS"' in mfa_header.replace(" ", "")


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_verify_sender_success(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    svc._store_pending_mfa("01012345678", "tx-abc")
    mock_request.return_value = (
        200,
        {"senderIds": [{"phoneNumber": "01012345678", "status": "ACTIVE"}]},
    )

    result = svc.verify_sender("01012345678", "123456")

    assert result == {"ok": True, "phone_number": "01012345678", "status": "ACTIVE"}
    assert "01012345678" not in svc._pending_mfa


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_verify_sender_without_pending_session(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")

    result = svc.verify_sender("01012345678", "123456")

    assert result == {"error": "인증코드 요청을 먼저 진행해주세요. (10분 이내)"}
    mock_request.assert_not_called()


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_delete_sender_active_requires_inactive_first(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    mock_request.side_effect = [
        (
            200,
            {"senderIds": [{"phoneNumber": "01012345678", "status": "ACTIVE"}]},
        ),
        (200, {"senderIds": [{"phoneNumber": "01012345678", "status": "INACTIVE"}]}),
        (200, {"senderIds": []}),
    ]

    result = svc.delete_sender("01012345678")

    assert result == {"ok": True, "phone_number": "01012345678"}
    assert mock_request.call_args_list[1][0][0] == "PUT"
    assert mock_request.call_args_list[2][0][0] == "DELETE"


@patch("app.services.solapi_service._solapi_request")
@patch("app.services.solapi_service._solapi_credentials")
def test_delete_sender_not_found(mock_creds, mock_request):
    mock_creds.return_value = ("key", "secret")
    mock_request.return_value = (200, {"senderIds": []})

    result = svc.delete_sender("01012345678")

    assert result == {"error": "등록되지 않은 발신번호입니다."}
