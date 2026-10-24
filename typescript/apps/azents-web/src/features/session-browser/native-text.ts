/** Diff only text typed in this local receiver, never a remote field snapshot. */
export function browserNativeTextChange(
  previous: string,
  next: string,
): { remove: number; insert: string } {
  const segmenter = new Intl.Segmenter("en", { granularity: "grapheme" });
  const before = [...segmenter.segment(previous)].map((part) => part.segment);
  const after = [...segmenter.segment(next)].map((part) => part.segment);
  let common = 0;
  while (common < before.length && before[common] === after[common]) {
    common += 1;
  }
  return {
    remove: before.length - common,
    insert: after.slice(common).join(""),
  };
}
