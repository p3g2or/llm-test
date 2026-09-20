export type Category = "work" | "personal" | "ideas";

export interface NewNote {
  title: string;
  body: string;
  category: Category;
}

export interface Note extends NewNote {
  id: string;
  created_at: string;
}

export interface PublicConfig {
  board_title: string;
  title_limit: number;
  body_limit: number;
  categories: Category[];
}

export interface Summary {
  total: number;
  by_category: Record<Category, number>;
}
