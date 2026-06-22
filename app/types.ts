export interface Role {
  title: string;
  url: string;
  score: number;
  matched: boolean;
  best_role: string;
}

export interface Company {
  company: string;
  url: string;
  error: string | null;
  match_count: number;
  top_score: number;
  roles: Role[];
}

export interface Snapshot {
  generated_at: string;
  threshold: number;
  embedding_backend: string;
  ideal_roles: string[];
  company_count: number;
  total_matches: number;
  sample?: boolean;
  companies: Company[];
}
