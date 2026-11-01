"""Attachment endpoints: upload, download, and delete attachments.

Limits: single file <= 100MB (104,857,600 bytes).
Stored safely in the server data directory under `data/attachments/`.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from ..config import get_settings
from ..models import User
from ..security import timeline_owner
from ..timeutil import utcnow

router = APIRouter(prefix="/attachments", tags=["attachments"])
log = logging.getLogger("campushub.api.attachments")

# 单文件最大 100MB
MAX_ATTACHMENT_SIZE = 100 * 1024 * 1024


def _get_attachments_dir() -> Path:
    settings = get_settings()
    d = Path(settings.data_dir) / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return cleaned or "file"


@router.post("", summary="Upload an attachment (max 100MB)")
async def upload_attachment(
    file: UploadFile = File(...),
    user: User = Depends(timeline_owner),
) -> dict[str, Any]:
    """上传一个附件文件至云端存储，每个文件不超过 100MB。"""
    filename = _sanitize_filename(file.filename or "attachment")
    file_id = f"{uuid4().hex[:12]}"
    store_name = f"{file_id}_{filename}"
    target_path = _get_attachments_dir() / store_name

    size = 0
    try:
        with open(target_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB 块流式写入
                size += len(chunk)
                if size > MAX_ATTACHMENT_SIZE:
                    buffer.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="文件体积超出限制（单个文件最大支持 100MB）",
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        log.error("Attachment upload failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"附件写入云端失败: {exc}",
        ) from exc
    finally:
        await file.close()

    mime_type = file.content_type or "application/octet-stream"
    created_at = utcnow().isoformat()

    return {
        "id": file_id,
        "name": filename,
        "size": size,
        "mime": mime_type,
        "url": f"/api/attachments/{file_id}",
        "created_at": created_at,
    }


@router.get("/{file_id}", summary="Download / view an attachment")
def get_attachment(
    file_id: str,
) -> FileResponse:
    """根据文件 ID 从云端下载或在线预览附件。"""
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", file_id)
    if not clean_id:
        raise HTTPException(status_code=404, detail="附件不存在")

    attachments_dir = _get_attachments_dir()
    # 按照前缀寻找匹配的文件
    matched = list(attachments_dir.glob(f"{clean_id}_*"))
    if not matched:
        raise HTTPException(status_code=404, detail="附件文件未找到或已被清理")

    file_path = matched[0]
    filename = file_path.name[len(clean_id) + 1 :]
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.delete("/{file_id}", summary="Delete an attachment from cloud storage")
def delete_attachment(
    file_id: str,
    user: User = Depends(timeline_owner),
) -> dict[str, Any]:
    """从云端永久移除附件文件。"""
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", file_id)
    if not clean_id:
        raise HTTPException(status_code=404, detail="附件不存在")

    attachments_dir = _get_attachments_dir()
    matched = list(attachments_dir.glob(f"{clean_id}_*"))
    for f in matched:
        f.unlink(missing_ok=True)

    return {"ok": True, "message": "附件已从云端移除"}
