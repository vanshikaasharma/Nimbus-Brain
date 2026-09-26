export type Chunk = {
  doc_path: string;
  section: string;
  body: string;
  score: number;
  page_number?: number | null;
  source_id?: string | null;
};
