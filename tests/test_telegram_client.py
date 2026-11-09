"""Tests for Telegram client, retries, and 429 rate limit backoff."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from backupbot.telegram.client import TelegramAPIError, TelegramClient


def test_send_message_success():
    session = MagicMock()
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 12345}}
    session.request.return_value = mock_response

    client = TelegramClient(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", session=session)
    msg_id = client.send_message(chat_id="-100123", text="Hello from BackupBot")

    assert msg_id == 12345
    assert session.request.called
    args, kwargs = session.request.call_args
    assert kwargs["data"]["text"] == "Hello from BackupBot"
    assert kwargs["data"]["chat_id"] == "-100123"


def test_send_document_success(tmp_path):
    doc_file = tmp_path / "test_doc.tar.gz.age"
    doc_file.write_bytes(b"encrypted binary content")

    session = MagicMock()
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 54321}}
    session.request.return_value = mock_response

    client = TelegramClient(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", session=session)
    msg_id = client.send_document(
        chat_id="-100123",
        file_path=str(doc_file),
        filename="custom_name.tar.gz.age",
        caption="My test caption",
    )

    assert msg_id == 54321
    assert session.request.called
    args, kwargs = session.request.call_args
    assert kwargs["data"]["caption"] == "My test caption"
    assert "document" in kwargs["files"]


def test_telegram_429_retry_after():
    session = MagicMock()

    # First attempt: 429 Too Many Requests with retry_after = 1
    resp_429 = MagicMock()
    resp_429.ok = False
    resp_429.status_code = 429
    resp_429.json.return_value = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests: retry after 1",
        "parameters": {"retry_after": 1},
    }

    # Second attempt: Success
    resp_ok = MagicMock()
    resp_ok.ok = True
    resp_ok.status_code = 200
    resp_ok.json.return_value = {"ok": True, "result": {"message_id": 777}}

    session.request.side_effect = [resp_429, resp_ok]

    with patch("time.sleep") as mock_sleep:
        client = TelegramClient(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", session=session)
        msg_id = client.send_message("-100123", "Test 429 retry")

        assert msg_id == 777
        assert session.request.call_count == 2
        mock_sleep.assert_called_once_with(1.5)  # retry_after (1) + 0.5 buffer


def test_telegram_network_error_retry():
    session = MagicMock()
    # First attempt: Network Timeout
    # Second attempt: Success
    resp_ok = MagicMock()
    resp_ok.ok = True
    resp_ok.status_code = 200
    resp_ok.json.return_value = {"ok": True, "result": {"message_id": 888}}

    session.request.side_effect = [requests.Timeout("Connection timed out"), resp_ok]

    with patch("time.sleep"):
        client = TelegramClient(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", max_retries=3, session=session)
        msg_id = client.send_message("-100123", "Test timeout retry")
        assert msg_id == 888
        assert session.request.call_count == 2


def test_telegram_api_error_raises():
    session = MagicMock()
    resp_bad = MagicMock()
    resp_bad.ok = False
    resp_bad.status_code = 400
    resp_bad.json.return_value = {"ok": False, "error_code": 400, "description": "Chat not found"}
    session.request.return_value = resp_bad

    client = TelegramClient(bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", max_retries=1, session=session)
    with pytest.raises(TelegramAPIError) as exc:
        client.send_message("-100123", "Test error")

    assert "Chat not found" in str(exc.value)

@pytest.mark.parametrize('document', [False, True])
def test_forum_topic_applies_to_messages_and_documents(tmp_path, document):
    session = MagicMock()
    response = session.request.return_value
    response.ok = True
    response.status_code = 200
    response.json.return_value = {'ok': True, 'result': {'message_id': 42}}
    client = TelegramClient('123:TEST', session=session, message_thread_id=17)
    if document:
        path = tmp_path / 'backup.age'
        path.write_bytes(b'encrypted')
        client.send_document('-100123', str(path), 'backup.age', 'backup')
    else:
        client.send_message('-100123', 'backup status')
    assert session.request.call_args.kwargs['data']['message_thread_id'] == 17


def test_ordinary_chat_does_not_send_topic_id():
    session = MagicMock()
    response = session.request.return_value
    response.ok = True
    response.status_code = 200
    response.json.return_value = {'ok': True, 'result': {'message_id': 42}}
    TelegramClient('123:TEST', session=session).send_message('123', 'backup status')
    assert 'message_thread_id' not in session.request.call_args.kwargs['data']
