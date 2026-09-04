export type ChatAction =
  | { type: "command"; name: string }
  | { type: "goal" }
  | { type: "skill"; skill_path: string }
  | {
      type: "create_git_worktree";
      source_project_path: string;
      starting_ref: string;
    }
  | { type: "cleanup_orphan_git_worktrees" };
