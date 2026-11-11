/** Return a skill without whitespace or a Markdown/list bullet prefix. */
export function normalizeSkill(skill: string): string {
  return skill.trim().replace(/^[-–—]\s+/, "").trim();
}

export function normalizeSkills(skills: string[]): string[] {
  return skills.map(normalizeSkill).filter(Boolean);
}
