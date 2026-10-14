import type { ToolkitConfigResponse } from "@azents/public-client";

export const previewProviders = [
  {
    type: "github",
    label: "GitHub",
    description: "저장소, 이슈, Pull Request와 자동화 작업",
  },
  {
    type: "notion",
    label: "Notion",
    description: "페이지와 데이터베이스 조회 및 편집",
  },
  {
    type: "sentry",
    label: "Sentry",
    description: "오류와 이벤트 조사 및 이슈 관리",
  },
  { type: "mcp", label: "MCP", description: "직접 지정한 MCP 서버의 도구" },
  {
    type: "brave_search",
    label: "Brave Search",
    description: "웹, 뉴스, 이미지와 동영상 검색",
  },
  {
    type: "gcp",
    label: "Google Cloud",
    description: "프로젝트와 클라우드 리소스 관리",
  },
  { type: "aws", label: "AWS", description: "AWS 서비스와 리소스 관리" },
  {
    type: "kubernetes",
    label: "Kubernetes",
    description: "클러스터 리소스 조회 및 관리",
  },
  {
    type: "google_analytics",
    label: "Google Analytics",
    description: "사이트와 앱의 분석 보고서 조회",
  },
  {
    type: "envvar",
    label: "환경 변수",
    description: "Agent 실행 환경에 변수 전달",
  },
];

function toolkit(
  id: string,
  toolkitType: string,
  name: string,
  description: string,
  config: ToolkitConfigResponse["config"],
  enabled = true,
): ToolkitConfigResponse {
  return {
    id,
    workspace_id: "workspace-preview",
    toolkit_type: toolkitType,
    slug: id,
    name,
    description,
    config,
    prompt: null,
    has_credentials: false,
    enabled,
    always_expose_tools: false,
    oauth_connection: null,
    authorization_state: null,
    github_user_connection: null,
    created_at: "2026-10-14T00:00:00Z",
    updated_at: "2026-10-14T00:00:00Z",
  };
}

/** Synthetic response-shaped examples; no credentials, grants, or live health claims. */
export const previewToolkits: ToolkitConfigResponse[] = [
  toolkit(
    "engineering_github",
    "github",
    "개발팀 GitHub",
    "코드 변경과 이슈를 함께 관리합니다.",
    {
      github_auth_type: "github_app",
      toolsets: ["repos", "issues", "pull_requests"],
      inject_runtime_environment: false,
    },
  ),
  {
    ...toolkit(
      "team_notion",
      "notion",
      "팀 문서",
      "기획과 운영 문서를 살펴봅니다.",
      { timeout: 30 },
    ),
    oauth_connection: { status: "reconnect_required" },
  },
  toolkit(
    "research_search",
    "brave_search",
    "리서치 검색",
    "자료 조사에 사용할 웹 검색입니다.",
    { country: "KR", search_lang: "ko", safesearch: "moderate" },
  ),
  toolkit(
    "production_cluster",
    "kubernetes",
    "운영 클러스터",
    "운영 리소스를 읽기 전용으로 조회합니다.",
    {
      clusters: [{ name: "production" }],
      read_only: true,
      allowed_namespaces: ["apps"],
      denied_kinds: ["Secret"],
    },
    false,
  ),
  toolkit(
    "cloud_operations",
    "aws",
    "클라우드 운영",
    "서울 리전의 AWS 리소스를 관리합니다.",
    { region: "ap-northeast-2" },
  ),
  toolkit(
    "issue_monitoring",
    "sentry",
    "서비스 오류 조사",
    "서비스의 오류와 이벤트를 조사합니다.",
    { enabled_skills: ["inspect", "triage"] },
  ),
];
