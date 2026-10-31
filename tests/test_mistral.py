import pytest
from mistral_extension import build_request, parse_response, MistralError


def test_pdf_ocr_contains_blocks_and_table_option():
    request = build_request(b"%PDF-1.4 text", "application/pdf", {"table_format": "html"})
    assert request["document"]["type"] == "document_url"
    assert request["include_blocks"] is True
    assert request["table_format"] == "html"


def test_scanned_pdf_annotation_uses_schema():
    schema = {"type": "object", "properties": {"total": {"type": "number"}}}
    request = build_request(b"%PDF-1.4 scan", "application/pdf", {"schema": schema})
    assert request["document_annotation_format"]["json_schema"]["schema"] == schema
    assert request["pages"] == list(range(8))


def test_table_and_annotation_outputs():
    text, structured = parse_response(
        {
            "pages": [{"markdown": "| a | b |", "tables": [{"content": "| 1 | 2 |"}]}],
            "document_annotation": '{"total":2}',
        },
        True,
    )
    assert text == "| a | b |"
    assert structured == {"total": 2}


@pytest.mark.parametrize("mime, data", [("text/plain", b"text"), ("application/pdf", b"bad")])
def test_rejects_unsupported_or_invalid_document(mime, data):
    with pytest.raises(MistralError):
        build_request(data, mime, {})


def test_invalid_schema_and_options_are_rejected():
    with pytest.raises(MistralError):
        build_request(b"%PDF-1.4", "application/pdf", {"schema": []})
    with pytest.raises(MistralError):
        build_request(b"%PDF-1.4", "application/pdf", {"table_format": "other"})


def test_missing_credentials_does_not_read_artifact(monkeypatch):
    import mistral_extension as ext

    monkeypatch.setattr(ext, "runtime_context_from_payload", lambda _: None)
    monkeypatch.setattr(ext, "read_artifact_bytes", lambda *a, **k: pytest.fail("must not read"))
    response = ext.handle_payload(
        {
            "action": {
                "action_id": "process_document",
                "input": {"artifact_handle": "a"},
                "target": {"connection": {}},
            }
        }
    )
    assert response["error_code"] == "invalid_connection"


def test_timeout_reports_unknown_outcome_without_retry(monkeypatch):
    import mistral_extension as ext

    calls = []
    monkeypatch.setattr(ext, "resolve_pinned_ips", lambda *a, **k: ["1.1.1.1"])

    def fail(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()

    monkeypatch.setattr(ext, "open_pinned_url", fail)
    with pytest.raises(MistralError, match="outcome may be unknown"):
        ext.post_ocr({}, "key", 1)
    assert len(calls) == 1


def test_end_to_end_mock_saves_complete_response(monkeypatch):
    import mistral_extension as ext

    saved = []
    response = {
        "pages": [
            {
                "markdown": "Scanned text",
                "blocks": [{"type": "text"}],
                "tables": [{"content": "| A |"}],
            }
        ],
        "document_annotation": '{"total": 3}',
    }
    monkeypatch.setattr(ext, "runtime_context_from_payload", lambda _: None)
    monkeypatch.setattr(ext, "report_progress", lambda *_: None)
    monkeypatch.setattr(ext, "find_artifact_descriptor", lambda *a, **k: {"filename": "scan.pdf"})
    monkeypatch.setattr(ext, "read_artifact_bytes", lambda *a, **k: b"%PDF-1.4 scanned")
    monkeypatch.setattr(ext, "post_ocr", lambda *a, **k: (response, "req-1"))

    def save(payload, body, **kwargs):
        saved.append((body, kwargs))
        return {"artifact_handle": "artifact:result"}

    monkeypatch.setattr(ext, "write_artifact_bytes", save)
    payload = {
        "runtime_context": {"external_effect_id": "effect-1"},
        "action": {
            "action_id": "process_document",
            "input": {"artifact_handle": "artifact:input", "schema": {"type": "object"}},
            "target": {
                "connection": {"connection_type": "mistral_document", "secrets": {"api_key": "key"}}
            },
        },
    }
    result = ext.handle_payload(payload)
    assert result["ok"] is True
    assert result["result"]["text"] == "Scanned text"
    assert result["result"]["structured"] == {"total": 3}
    assert result["result"]["request_id"] == "req-1"
    assert __import__("json").loads(saved[0][0]) == response
    assert saved[0][1]["binding_key"] == "result_artifact_handle"


def test_http_error_includes_request_id_without_provider_body(monkeypatch):
    import io
    from urllib.error import HTTPError
    import mistral_extension as ext

    monkeypatch.setattr(ext, "resolve_pinned_ips", lambda *a, **k: ["1.1.1.1"])

    def fail(*args, **kwargs):
        raise HTTPError(
            "https://api.mistral.ai/v1/ocr",
            401,
            "unauthorized",
            {"x-request-id": "request-123"},
            io.BytesIO(b"secret body"),
        )

    monkeypatch.setattr(ext, "open_pinned_url", fail)
    with pytest.raises(MistralError) as caught:
        ext.post_ocr({}, "key", 1)
    assert caught.value.code == "provider_http_error"
    assert caught.value.request_id == "request-123"
    assert "secret body" not in str(caught.value)
