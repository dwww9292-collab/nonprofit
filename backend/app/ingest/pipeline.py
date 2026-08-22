"""수집 파이프라인: 파싱 → diff → 중복판정 → 리드 생성/병합 → 스코어링.

크롤러(1차 고도화)는 parse 결과(RawRow 리스트)만 만들어 ingest_rows()를 그대로 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.enums import (
    BatchStatus,
    DedupResult,
    SourceCode,
)
from app.ingest.base import ParseError, ParseResult, RawRow, file_sha256
from app.ingest.parsers import get_parser, parse_existing_customers
from app.models import ExistingCustomer, IngestBatch, Lead, LeadSource, RawRecord, Source
from app.services.dedup import (
    LeadCandidate,
    find_duplicate,
    find_possible_duplicate,
    match_existing_customer,
    merge_candidate_into_lead,
)
from app.services.normalize import (
    clean_biz_reg_no,
    clean_corp_reg_no,
    clean_text,
    extract_district,
    extract_region_code,
    normalize_org_name,
)
from app.services.scoring import ScoringConfig, determine_stage_signal, score_lead


@dataclass
class IngestResult:
    batch_id: int | None = None
    total_rows: int = 0
    new_leads: int = 0
    merged_leads: int = 0
    dup_skipped: int = 0
    customer_skipped: int = 0
    error_rows: int = 0
    revoked_marked: int = 0
    is_first_upload: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


@dataclass
class PreviewResult:
    header_map: dict[str, str]
    unmapped_headers: list[str]
    sheet_name: str | None
    total_rows: int
    is_first_upload: bool
    duplicate_file: bool
    preview_rows: list[dict]
    problems: list[str]


def _get_source(db: Session, source_code: str) -> Source:
    src = db.scalars(select(Source).where(Source.code == source_code)).first()
    if src is None:
        raise ParseError(f"등록되지 않은 소스입니다: {source_code}")
    return src


def _previous_batch(db: Session, source_id: int, exclude_batch_id: int | None = None) -> IngestBatch | None:
    stmt = (
        select(IngestBatch)
        .where(IngestBatch.source_id == source_id, IngestBatch.status == BatchStatus.PARSED)
        .order_by(IngestBatch.created_at.desc())
    )
    if exclude_batch_id is not None:
        stmt = stmt.where(IngestBatch.id != exclude_batch_id)
    return db.scalars(stmt).first()


def _previous_keys(db: Session, batch_id: int) -> set[str]:
    rows = db.execute(
        select(RawRecord.match_key).where(RawRecord.batch_id == batch_id, RawRecord.match_key.is_not(None))
    ).all()
    return {r[0] for r in rows}


def preview_file(
    db: Session,
    *,
    source_code: str,
    content: bytes,
    file_name: str,
    region_override: str | None = None,
    limit: int = 20,
) -> PreviewResult:
    """업로드 확정 전 미리보기 (docs/05-screens.md 6번 화면)."""
    src = _get_source(db, source_code)
    parser = get_parser(source_code)
    parsed = parser.parse(content, file_name)

    prev = _previous_batch(db, src.id)
    file_hash = file_sha256(content)
    dup_file = (
        db.scalars(
            select(IngestBatch).where(
                IngestBatch.source_id == src.id,
                IngestBatch.file_hash == file_hash,
                IngestBatch.status == BatchStatus.PARSED,
            )
        ).first()
        is not None
    )

    problems: list[str] = []
    if parsed.unmapped_headers:
        problems.append("매핑되지 않은 열: " + ", ".join(parsed.unmapped_headers[:10]))
    if dup_file:
        problems.append("동일한 파일이 이미 처리된 이력이 있습니다 (file_hash 일치).")
    if prev is None:
        problems.append(
            f"최초 업로드입니다: 직전 배치가 없어 {parsed.total_rows}건 전체가 리드 생성 대상이 됩니다."
        )

    preview_rows: list[dict] = []
    now = datetime.now(UTC)
    for row in parsed.rows[:limit]:
        item: dict = {"row_no": row.row_no, "payload": row.payload}
        if row.error:
            item["error"] = row.error
        else:
            try:
                cand = parser.to_candidate(row, collected_at=now, region_override=region_override)
                item["mapped"] = {
                    "org_name": cand.org_name,
                    "org_name_norm": cand.org_name_norm,
                    "org_type": cand.org_type,
                    "corp_reg_no": cand.corp_reg_no,
                    "biz_reg_no": cand.biz_reg_no,
                    "region_code": cand.region_code,
                    "district": cand.district,
                    "address": cand.address,
                    "representative": cand.representative,
                    "established_at": cand.established_at.isoformat() if cand.established_at else None,
                    "designated_at": cand.designated_at.isoformat() if cand.designated_at else None,
                }
            except ValueError as exc:
                item["error"] = str(exc)
        preview_rows.append(item)

    error_count = sum(1 for r in preview_rows if r.get("error"))
    if error_count:
        problems.append(f"미리보기 {len(preview_rows)}행 중 {error_count}행에서 문제가 감지됐습니다.")

    return PreviewResult(
        header_map=parsed.header_map,
        unmapped_headers=parsed.unmapped_headers,
        sheet_name=parsed.sheet_name,
        total_rows=parsed.total_rows,
        is_first_upload=prev is None,
        duplicate_file=dup_file,
        preview_rows=preview_rows,
        problems=problems,
    )


def create_lead_from_candidate(
    db: Session,
    cand: LeadCandidate,
    source: Source,
    cfg: ScoringConfig,
    *,
    is_existing_customer: bool = False,
) -> Lead:
    collected = cand.collected_at or datetime.now(UTC)
    lead = Lead(
        org_name=cand.org_name,
        org_name_norm=cand.org_name_norm,
        org_type=cand.org_type,
        corp_reg_no=cand.corp_reg_no,
        biz_reg_no=cand.biz_reg_no,
        region_code=cand.region_code,
        district=cand.district,
        address=cand.address,
        representative=cand.representative,
        phone=cand.phone,
        email=cand.email,
        homepage_url=cand.homepage_url,
        established_at=cand.established_at,
        designated_at=cand.designated_at,
        purpose=cand.purpose,
        authority=cand.authority,
        memo=cand.memo,
        asset_size=cand.asset_size,
        is_existing_customer=is_existing_customer,
        source_id=source.id,
        collected_at=collected,
    )
    lead.stage_signal = determine_stage_signal(cand.established_at, cand.designated_at, collected)
    score_lead(cfg, lead, reference=collected)
    if is_existing_customer:
        # PENALTY.EXISTING_CUSTOMER: 점수 0 / 등급 D 강제
        lead.score = 0
        lead.grade = "D"
        lead.score_breakdown = {"PENALTY.EXISTING_CUSTOMER": 0, "total": 0}
    db.add(lead)
    db.flush()
    return lead


def _link_source(db: Session, lead: Lead, source: Source, batch_id: int | None) -> None:
    """리드-소스 출처를 기록. 같은 배치에 동일 리드가 여러 행으로 들어와도 안전해야 한다.

    세션이 autoflush=False라 SELECT로는 같은 배치 안의 미flush 삽입을 못 본다.
    (기재부/행안부 실파일처럼 한 파일에 같은 단체가 여러 행 있는 경우 유니크 제약 위반이 났다.)
    DB의 유니크 제약에 맡기고 ON CONFLICT DO NOTHING으로 처리한다.
    """
    db.execute(
        pg_insert(LeadSource.__table__)
        .values(lead_id=lead.id, source_id=source.id, batch_id=batch_id)
        .on_conflict_do_nothing(constraint="uq_lead_source_batch")
    )


def ingest_rows(
    db: Session,
    *,
    batch: IngestBatch,
    source: Source,
    candidates: list[tuple[RawRow, LeadCandidate | None, str | None]],
    previous_keys: set[str] | None = None,
) -> IngestResult:
    """RawRow+후보 리스트를 받아 리드로 반영. 크롤러도 이 함수를 재사용한다.

    candidates: (원본행, 후보(None이면 에러행), 에러메시지)
    previous_keys: 직전 배치의 match_key 집합. 여기에 이미 있는 행은 diff상 신규가 아니다.
    """
    cfg = ScoringConfig.load(db)
    result = IngestResult(batch_id=batch.id, total_rows=len(candidates))
    prev = previous_keys or set()
    result.is_first_upload = not prev
    seen_keys: set[str] = set()

    for row, cand, err in candidates:
        if cand is None:
            db.add(
                RawRecord(
                    batch_id=batch.id,
                    row_no=row.row_no,
                    payload=row.payload,
                    dedup_result=DedupResult.ERROR,
                    error_message=err or row.error,
                )
            )
            result.error_rows += 1
            result.errors.append({"row_no": row.row_no, "message": err or row.error, "payload": row.payload})
            continue

        key = cand.match_key
        seen_keys.add(key)

        # --- diff: 직전 배치에 이미 있던 행은 신규가 아님 ---
        if key in prev:
            db.add(
                RawRecord(
                    batch_id=batch.id,
                    row_no=row.row_no,
                    payload=row.payload,
                    match_key=key,
                    dedup_result=DedupResult.SKIPPED_DUP,
                )
            )
            result.dup_skipped += 1
            continue

        # --- 기고객 필터 ---
        customer = match_existing_customer(db, cand)

        # --- 중복 판정 1~3 ---
        match = find_duplicate(db, cand)
        if match.lead is not None:
            changed = merge_candidate_into_lead(match.lead, cand)
            if changed:
                match.lead.stage_signal = determine_stage_signal(
                    match.lead.established_at, match.lead.designated_at, match.lead.collected_at
                )
                score_lead(cfg, match.lead, reference=match.lead.collected_at)
                if match.lead.is_existing_customer:
                    match.lead.score = 0
                    match.lead.grade = "D"
            _link_source(db, match.lead, source, batch.id)
            db.add(
                RawRecord(
                    batch_id=batch.id,
                    row_no=row.row_no,
                    payload=row.payload,
                    match_key=key,
                    lead_id=match.lead.id,
                    dedup_result=DedupResult.MERGED,
                )
            )
            result.merged_leads += 1
            continue

        lead = create_lead_from_candidate(
            db, cand, source, cfg, is_existing_customer=customer is not None
        )
        possible = find_possible_duplicate(db, cand)
        if possible is not None and possible.id != lead.id:
            lead.possible_dup_lead_id = possible.id
        _link_source(db, lead, source, batch.id)
        db.add(
            RawRecord(
                batch_id=batch.id,
                row_no=row.row_no,
                payload=row.payload,
                match_key=key,
                lead_id=lead.id,
                dedup_result=DedupResult.SKIPPED_CUSTOMER if customer else DedupResult.NEW,
            )
        )
        if customer:
            result.customer_skipped += 1
        else:
            result.new_leads += 1

    # --- 누계에서 사라진 행 → 지정취소 가능성 (기재부 소스 한정) ---
    if source.code == SourceCode.MOEF_DESIGNATION and prev:
        vanished = prev - seen_keys
        if vanished:
            result.revoked_marked = _mark_possible_revoked(db, vanished)

    batch.total_rows = result.total_rows
    batch.new_leads = result.new_leads
    batch.merged_leads = result.merged_leads
    batch.dup_skipped = result.dup_skipped
    batch.customer_skipped = result.customer_skipped
    batch.error_rows = result.error_rows
    batch.status = BatchStatus.PARSED
    db.flush()
    return result


def _mark_possible_revoked(db: Session, vanished_keys: set[str]) -> int:
    lead_ids = {
        r[0]
        for r in db.execute(
            select(RawRecord.lead_id).where(
                RawRecord.match_key.in_(vanished_keys), RawRecord.lead_id.is_not(None)
            )
        ).all()
    }
    count = 0
    for lead_id in lead_ids:
        lead = db.get(Lead, lead_id)
        if lead and not lead.possible_revoked:
            lead.possible_revoked = True
            count += 1
    return count


def ingest_file(
    db: Session,
    *,
    source_code: str,
    content: bytes,
    file_name: str,
    uploaded_by: int,
    period_label: str | None = None,
    region_override: str | None = None,
) -> tuple[IngestBatch, IngestResult]:
    """파일 업로드 확정 처리."""
    src = _get_source(db, source_code)
    parser = get_parser(source_code)

    batch = IngestBatch(
        source_id=src.id,
        file_name=file_name,
        file_hash=file_sha256(content),
        period_label=period_label,
        status=BatchStatus.PENDING,
        uploaded_by=uploaded_by,
    )
    db.add(batch)
    db.flush()

    try:
        parsed: ParseResult = parser.parse(content, file_name)
    except ParseError as exc:
        batch.status = BatchStatus.FAILED
        batch.error_message = str(exc)
        db.flush()
        return batch, IngestResult(batch_id=batch.id, errors=[{"message": str(exc)}])

    prev_batch = _previous_batch(db, src.id, exclude_batch_id=batch.id)
    prev_keys = _previous_keys(db, prev_batch.id) if prev_batch else set()

    now = datetime.now(UTC)
    candidates: list[tuple[RawRow, LeadCandidate | None, str | None]] = []
    for row in parsed.rows:
        if row.error:
            candidates.append((row, None, row.error))
            continue
        try:
            cand = parser.to_candidate(row, collected_at=now, region_override=region_override)
            candidates.append((row, cand, None))
        except ValueError as exc:
            candidates.append((row, None, str(exc)))

    result = ingest_rows(db, batch=batch, source=src, candidates=candidates, previous_keys=prev_keys)
    result.is_first_upload = prev_batch is None
    if parsed.unmapped_headers:
        result.warnings.append("매핑되지 않은 열: " + ", ".join(parsed.unmapped_headers[:10]))
    return batch, result


# --- 기고객 명단 업로드 (upsert + 전체 리드 재매칭) ---


@dataclass
class CustomerUploadResult:
    total_rows: int = 0
    inserted: int = 0
    updated: int = 0
    error_rows: int = 0
    retagged_leads: int = 0
    errors: list[dict] = field(default_factory=list)


def _find_customer(db: Session, corp: str | None, biz: str | None, norm: str) -> ExistingCustomer | None:
    if corp:
        hit = db.scalars(select(ExistingCustomer).where(ExistingCustomer.corp_reg_no == corp)).first()
        if hit:
            return hit
    if biz:
        hit = db.scalars(select(ExistingCustomer).where(ExistingCustomer.biz_reg_no == biz)).first()
        if hit:
            return hit
    return db.scalars(select(ExistingCustomer).where(ExistingCustomer.org_name_norm == norm)).first()


def upload_existing_customers(db: Session, *, content: bytes, file_name: str) -> CustomerUploadResult:
    """docs/04-data-sources.md 기고객 명단: upsert 후 기존 리드 전체 재매칭."""
    parsed = parse_existing_customers(content, file_name)
    res = CustomerUploadResult(total_rows=parsed.total_rows)

    for row in parsed.rows:
        if row.error:
            res.error_rows += 1
            res.errors.append({"row_no": row.row_no, "message": row.error})
            continue
        f = row.fields
        org_name = clean_text(f.get("org_name"), 200)
        if not org_name:
            res.error_rows += 1
            res.errors.append({"row_no": row.row_no, "message": "법인명이 비어 있습니다."})
            continue
        norm = normalize_org_name(org_name)
        corp = clean_corp_reg_no(clean_text(f.get("corp_reg_no")))
        biz = clean_biz_reg_no(clean_text(f.get("biz_reg_no")))
        address = clean_text(f.get("address"), 300)
        products_raw = clean_text(f.get("products")) or ""
        products = [p.strip() for p in products_raw.replace(",", ";").split(";") if p.strip()]

        hit = _find_customer(db, corp, biz, norm)
        if hit is None:
            hit = ExistingCustomer(org_name=org_name, org_name_norm=norm)
            db.add(hit)
            res.inserted += 1
        else:
            res.updated += 1
        hit.org_name = org_name
        hit.org_name_norm = norm
        hit.corp_reg_no = corp or hit.corp_reg_no
        hit.biz_reg_no = biz or hit.biz_reg_no
        hit.address = address or hit.address
        hit.region_code = extract_region_code(address) if address else hit.region_code
        if hit.region_code == "99":
            hit.region_code = None
        hit.products = products or hit.products
        hit.note = clean_text(f.get("note"), 300) or hit.note

    db.flush()
    res.retagged_leads = retag_existing_customers(db)
    return res


def retag_existing_customers(db: Session) -> int:
    """기존 리드 전체에 대해 기고객 재매칭 배치."""
    cfg = ScoringConfig.load(db)
    leads = db.scalars(select(Lead).where(Lead.deleted_at.is_(None))).all()
    changed = 0
    for lead in leads:
        cand = LeadCandidate(
            org_name=lead.org_name,
            org_name_norm=lead.org_name_norm,
            corp_reg_no=lead.corp_reg_no,
            biz_reg_no=lead.biz_reg_no,
            region_code=lead.region_code,
        )
        is_customer = match_existing_customer(db, cand) is not None
        if is_customer == lead.is_existing_customer:
            continue
        lead.is_existing_customer = is_customer
        if is_customer:
            lead.score = 0
            lead.grade = "D"
            lead.score_breakdown = {"PENALTY.EXISTING_CUSTOMER": 0, "total": 0}
        else:
            score_lead(cfg, lead, reference=lead.collected_at)
        changed += 1
    db.flush()
    return changed


# district 재계산 등에 쓰이는 헬퍼 (수기입력 폼에서 재사용)
def build_manual_candidate(payload: dict, source_code: str) -> LeadCandidate:
    from app.services.normalize import (
        guess_org_type,
        normalize_url,
        parse_date,
    )

    org_name = clean_text(payload.get("org_name"), 200)
    if not org_name:
        raise ValueError("법인명은 필수입니다.")
    address = clean_text(payload.get("address"), 300)
    region_code = payload.get("region_code") or extract_region_code(address)
    return LeadCandidate(
        org_name=org_name,
        org_name_norm=normalize_org_name(org_name),
        org_type=payload.get("org_type") or guess_org_type(org_name),
        corp_reg_no=clean_corp_reg_no(clean_text(payload.get("corp_reg_no"))),
        biz_reg_no=clean_biz_reg_no(clean_text(payload.get("biz_reg_no"))),
        region_code=region_code,
        district=clean_text(payload.get("district"), 50) or extract_district(address),
        address=address,
        representative=clean_text(payload.get("representative"), 50),
        phone=clean_text(payload.get("phone"), 30),
        email=clean_text(payload.get("email"), 255),
        homepage_url=normalize_url(payload.get("homepage_url")),
        established_at=parse_date(payload.get("established_at")),
        designated_at=parse_date(payload.get("designated_at")),
        purpose=clean_text(payload.get("purpose")),
        authority=clean_text(payload.get("authority"), 100),
        memo=clean_text(payload.get("memo")),
        asset_size=payload.get("asset_size") or "ASSET_UNKNOWN",
        source_code=source_code,
        collected_at=datetime.now(UTC),
        raw=dict(payload),
    )
