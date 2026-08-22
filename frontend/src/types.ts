export type Role = 'ADMIN' | 'MANAGER' | 'SALES'

export interface User {
  id: number
  email: string
  name: string
  role: Role
  region_codes: string[] | null
  is_active: boolean
}

export interface EnumOption { code: string; label: string }

export interface EnumMeta {
  roles: EnumOption[]
  org_types: EnumOption[]
  lead_statuses: EnumOption[]
  deal_stages: EnumOption[]
  products: EnumOption[]
  lost_reasons: EnumOption[]
  activity_types: EnumOption[]
  asset_sizes: EnumOption[]
  stage_signals: EnumOption[]
  regions: EnumOption[]
  external_links: { code: string; label: string; url: string }[]
}

export interface Source {
  id: number
  code: string
  name: string
  collect_method: string
  is_active: boolean
  license_type: string | null
  crawl_note: string | null
}

export interface Lead {
  id: number
  org_name: string
  org_type: string
  region_code: string | null
  district: string | null
  established_at: string | null
  designated_at: string | null
  stage_signal: string
  score: number
  grade: string
  status: string
  assignee_id: number | null
  assignee_name: string | null
  source_code: string | null
  collected_at: string
  is_existing_customer: boolean
  possible_dup_lead_id: number | null
  possible_revoked: boolean
}

export interface LeadDetail extends Lead {
  org_name_norm: string
  corp_reg_no: string | null
  biz_reg_no: string | null
  address: string | null
  representative: string | null
  phone: string | null
  email: string | null
  homepage_url: string | null
  purpose: string | null
  authority: string | null
  memo: string | null
  asset_size: string
  score_breakdown: Record<string, number> | null
  lost_reason: string | null
  assigned_at: string | null
  first_contacted_at: string | null
  sources: Source[]
}

export interface Page<T> { items: T[]; total: number; page: number; size: number }

export interface Deal {
  id: number
  lead_id: number
  lead_name: string | null
  product_code: string
  stage: string
  amount: number | null
  probability: number | null
  expected_close: string | null
  closed_at: string | null
  lost_reason: string | null
  owner_id: number
  owner_name: string | null
  next_action_at: string | null
}

export interface Activity {
  id: number
  lead_id: number
  deal_id: number | null
  type: string
  summary: string
  next_action: string | null
  next_action_at: string | null
  actor_id: number
  actor_name: string | null
  occurred_at: string
}

export interface DashboardLeadBrief {
  id: number
  org_name: string
  score: number
  grade: string
  collected_at: string
  assignee_name: string | null
  days_since_assigned: number | null
}

export interface Dashboard {
  urgent_unassigned_count: number
  urgent_unassigned: DashboardLeadBrief[]
  stale_assigned_count: number
  stale_assigned: DashboardLeadBrief[]
  weekly_inflow: { week: string; source_code: string; count: number }[]
  grade_distribution: Record<string, number>
  pipeline_summary: { stage: string; count: number; amount: number }[]
  quarter_won: { product_code: string; count: number; amount: number }[]
  quarter_label: string
}

export interface PerformanceRow {
  user_id: number
  name: string
  assigned_leads: number
  contacted_leads: number
  contact_rate: number
  meetings: number
  proposals: number
  won_count: number
  won_amount: number
  avg_first_contact_hours: number | null
}

export interface Performance {
  period_label: string
  rows: PerformanceRow[]
  product_summary: { product_code: string; count: number; amount: number }[]
}

export interface IngestBatch {
  id: number
  source_code: string | null
  source_name: string | null
  file_name: string | null
  period_label: string | null
  status: string
  total_rows: number
  new_leads: number
  merged_leads: number
  dup_skipped: number
  customer_skipped: number
  error_rows: number
  error_message: string | null
  created_at: string
}

export interface IngestPreview {
  header_map: Record<string, string>
  unmapped_headers: string[]
  sheet_name: string | null
  total_rows: number
  is_first_upload: boolean
  duplicate_file: boolean
  preview_rows: { row_no: number; payload: Record<string, string>; mapped?: Record<string, string | null>; error?: string }[]
  problems: string[]
}

export interface IngestResult {
  batch_id: number | null
  status: string
  total_rows: number
  new_leads: number
  merged_leads: number
  dup_skipped: number
  customer_skipped: number
  error_rows: number
  revoked_marked: number
  is_first_upload: boolean
  warnings: string[]
  errors: { row_no?: number | null; message?: string; payload?: Record<string, string> }[]
}

export interface CustomerUploadResult {
  total_rows: number
  inserted: number
  updated: number
  error_rows: number
  retagged_leads: number
}

export interface ScoringSetting {
  id: number
  rule_key: string
  points: number
  description: string | null
  value_json: Record<string, unknown> | null
}

export interface DupCandidate {
  lead_id: number
  org_name: string
  address: string | null
  region_code: string | null
  status: string
  assignee_name: string | null
  match_reason: string
}

export interface DupCheckResponse {
  exact: DupCandidate | null
  similar: DupCandidate[]
  existing_customer: boolean
}

export interface AssigneeSuggestion {
  user_id: number
  name: string
  region_match: boolean
  open_lead_count: number
}
