/** Local operation identity; changing inputs or explicit abandonment invalidates old results. */
export class GitHubWizardOperations {
  private generation = 0;
  next(): number {
    this.generation += 1;
    return this.generation;
  }
  isCurrent(operation: number): boolean {
    return operation === this.generation;
  }
}

/** A late connect response must cancel only its newly created unpublished attempt. */
export function acceptGitHubCreationResult(
  current: boolean,
  attemptId: string,
  cancelExact: (attemptId: string) => void,
): boolean {
  if (current) {
    return true;
  }
  cancelExact(attemptId);
  return false;
}
