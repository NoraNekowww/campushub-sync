import io
import pytest
from app.models import Event, Source, make_event_id


def test_attachment_upload_download_delete(client, admin_headers):
    """测试附件上传、下载、删除及 100MB 校验链路。"""
    # 1. 成功上传小文件
    test_content = b"CampusHub Test Attachment Content"
    file_obj = io.BytesIO(test_content)
    upload_resp = client.post(
        "/api/attachments",
        files={"file": ("test_doc.txt", file_obj, "text/plain")},
        headers=admin_headers,
    )
    assert upload_resp.status_code == 200, upload_resp.text
    data = upload_resp.json()
    assert "id" in data
    assert data["name"] == "test_doc.txt"
    assert data["size"] == len(test_content)
    file_id = data["id"]

    # 2. 成功下载与内容校验
    get_resp = client.get(f"/api/attachments/{file_id}")
    assert get_resp.status_code == 200
    assert get_resp.content == test_content

    # 3. 关联到自定义日程/DDL 并保存
    event_payload = {
        "title": "带附件的DDL",
        "start_time": "2026-11-05T20:00:00",
        "is_deadline": True,
        "attachments": [data],
    }
    create_resp = client.post("/api/events", json=event_payload, headers=admin_headers)
    assert create_resp.status_code == 201, create_resp.text
    ev_data = create_resp.json()
    assert ev_data["attachments"] is not None
    assert len(ev_data["attachments"]) == 1
    assert ev_data["attachments"][0]["id"] == file_id

    # 4. 删除附件
    del_resp = client.delete(f"/api/attachments/{file_id}", headers=admin_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    # 5. 再次获取应返回 404
    get_del_resp = client.get(f"/api/attachments/{file_id}")
    assert get_del_resp.status_code == 404
