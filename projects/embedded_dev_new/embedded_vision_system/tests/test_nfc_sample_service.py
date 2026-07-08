from embedded_vision_system.hardware import MockNFCReader
from embedded_vision_system.nfc_sample_service import NFCSampleService


def test_nfc_sample_service_latches_readable_text_until_consumed_and_release():
    service = NFCSampleService(reader=MockNFCReader(), enabled=False)

    readable_payload = {
        "success": True,
        "material_id": "MAT001",
        "text": "MAT001",
        "raw": {"material_id_source": "tag_payload"},
    }
    empty_payload = {
        "success": False,
        "text": None,
        "error": "No NFC tag detected",
        "raw": {"mode": "pytest"},
    }
    next_readable_payload = {
        "success": True,
        "material_id": "MAT002",
        "text": "MAT002",
        "raw": {"material_id_source": "tag_payload"},
    }

    service.publish_result(readable_payload, source="poll")
    latched_snapshot = service.peek_latched_result()
    assert latched_snapshot["sample"]["material_id"] == "MAT001"

    service.publish_result(empty_payload, source="poll")
    assert service.peek_latched_result()["sample"]["material_id"] == "MAT001"

    assert service.mark_latched_result_consumed(latched_snapshot["sampled_at"]) is True
    assert service.peek_latched_result()["sample"] is None

    service.publish_result(readable_payload, source="poll")
    assert service.peek_latched_result()["sample"] is None

    service.publish_result(empty_payload, source="poll")
    service.publish_result(next_readable_payload, source="poll")
    assert service.peek_latched_result()["sample"]["material_id"] == "MAT002"


def test_nfc_sample_service_accepts_new_readable_tag_after_consuming_old_one():
    service = NFCSampleService(reader=MockNFCReader(), enabled=False)

    first_payload = {
        "success": True,
        "material_id": "MAT001",
        "text": "MAT001",
        "raw": {"material_id_source": "tag_payload"},
    }
    second_payload = {
        "success": True,
        "material_id": "MAT002",
        "text": "MAT002",
        "raw": {"material_id_source": "tag_payload"},
    }

    service.publish_result(first_payload, source="poll")
    first_snapshot = service.peek_latched_result()
    assert service.mark_latched_result_consumed(first_snapshot["sampled_at"]) is True

    service.publish_result(first_payload, source="poll")
    assert service.peek_latched_result()["sample"] is None

    service.publish_result(second_payload, source="poll")
    assert service.peek_latched_result()["sample"]["material_id"] == "MAT002"
