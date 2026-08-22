from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import DbSession, ManagerUp, write_audit
from app.core.enums import AuditAction, BatchStatus, CollectMethod, SourceCode
from app.ingest.base import ParseError
from app.ingest.pipeline import ingest_file, preview_file, upload_existing_customers
from app.models import IngestBatch, Source
from app.schemas import (
    BatchOut,
    CustomerUploadResponse,
    IngestResponse,
    PreviewResponse,
    SourceOut,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_UPLOAD_BYTES = 30 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "빈 파일입니다.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "파일이 너무 큽니다 (30MB 초과).")
    return content


@router.get("/sources", response_model=list[SourceOut])
def upload_sources(db: DbSession, user: ManagerUp) -> list[SourceOut]:
    rows = db.scalars(
        select(Source)
        .where(Source.collect_method == CollectMethod.FILE_UPLOAD, Source.is_active.is_(True))
        .order_by(Source.id)
    ).all()
    return [SourceOut.model_validate(s) for s in rows]


@router.post("/preview", response_model=PreviewResponse)
async def preview(
    db: DbSession,
    user: ManagerUp,
    source_code: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    region_override: Annotated[str | None, Form()] = None,
) -> PreviewResponse:
    content = await _read(file)
    try:
        result = preview_file(
            db,
            source_code=source_code,
            content=content,
            file_name=file.filename or "upload",
            region_override=region_override,
        )
    except (ParseError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return PreviewResponse(**result.__dict__)


@router.post("/commit", response_model=IngestResponse)
async def commit(
    db: DbSession,
    user: ManagerUp,
    source_code: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    period_label: Annotated[str | None, Form()] = None,
    region_override: Annotated[str | None, Form()] = None,
) -> IngestResponse:
    content = await _read(file)
    if source_code == SourceCode.MOEF_DESIGNATION and not period_label:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "기재부 파일은 기간(period_label) 입력이 필수입니다."
        )
    try:
        batch, result = ingest_file(
            db,
            source_code=source_code,
            content=content,
            file_name=file.filename or "upload",
            uploaded_by=user.id,
            period_label=period_label,
            region_override=region_override,
        )
    except (ParseError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    write_audit(
        db, user, AuditAction.INGEST, target_type="BATCH", target_id=batch.id,
        detail={"source": source_code, "new_leads": result.new_leads},
    )
    db.commit()
    return IngestResponse(
        batch_id=batch.id,
        status=batch.status,
        total_rows=result.total_rows,
        new_leads=result.new_leads,
        merged_leads=result.merged_leads,
        dup_skipped=result.dup_skipped,
        customer_skipped=result.customer_skipped,
        error_rows=result.error_rows,
        revoked_marked=result.revoked_marked,
        is_first_upload=result.is_first_upload,
        warnings=result.warnings + ([batch.error_message] if batch.error_message else []),
        errors=result.errors,
    )


@router.post("/existing-customers", response_model=CustomerUploadResponse)
async def upload_customers(
    db: DbSession, user: ManagerUp, file: Annotated[UploadFile, File()]
) -> CustomerUploadResponse:
    content = await _read(file)
    try:
        result = upload_existing_customers(db, content=content, file_name=file.filename or "customers.csv")
    except (ParseError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    write_audit(db, user, AuditAction.INGEST, target_type="CUSTOMER", detail=result.__dict__ | {"errors": []})
    db.commit()
    return CustomerUploadResponse(**result.__dict__)


@router.get("/batches", response_model=list[BatchOut])
def list_batches(db: DbSession, user: ManagerUp, limit: int = 50) -> list[BatchOut]:
    rows = db.scalars(select(IngestBatch).order_by(IngestBatch.created_at.desc()).limit(limit)).unique().all()
    out = []
    for b in rows:
        item = BatchOut.model_validate(b)
        item.source_code = b.source.code if b.source else None
        item.source_name = b.source.name if b.source else None
        out.append(item)
    return out


@router.get("/batches/{batch_id}/errors")
def batch_errors(batch_id: int, db: DbSession, user: ManagerUp) -> list[dict]:
    from app.models import RawRecord

    batch = db.get(IngestBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "배치를 찾을 수 없습니다.")
    rows = db.scalars(
        select(RawRecord).where(RawRecord.batch_id == batch_id, RawRecord.dedup_result == "ERROR")
    ).all()
    parsed_errors = [{"row_no": r.row_no, "error": r.error_message, "payload": r.payload} for r in rows]
    if parsed_errors:
        return parsed_errors
    if batch.status == BatchStatus.FAILED:
        return [{"row_no": None, "error": batch.error_message, "payload": {}}]
    return []
