{{- if .Values.server.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "azents.serverConfigMapName" . | quote }}
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "server") | nindent 4 }}
data:
  {{- range $key, $value := .Values.server.env }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}
  AZ_RDB_HOST: {{ include "azents.databaseHost" . | quote }}
  AZ_RDB_PORT: {{ .Values.database.external.port | quote }}
  AZ_RDB_USER: {{ .Values.database.external.user | quote }}
  AZ_RDB_DB_NAME: {{ .Values.database.external.database | quote }}
  AZ_RDB_USE_IAM_AUTH: {{ .Values.database.external.useIamAuth | quote }}
  AZ_RDB_REGION: {{ .Values.database.external.region | quote }}
  AZ_RDB_SSL_MODE: {{ .Values.database.external.sslMode | quote }}
  {{- $redisUrl := include "azents.redisConfigUrl" . }}
  {{- if $redisUrl }}
  AZ_REDIS_URL: {{ $redisUrl | quote }}
  {{- end }}
  {{- $objectStorageEndpoint := include "azents.objectStorageEndpoint" . }}
  {{- if $objectStorageEndpoint }}
  AZ_WORKSPACE_S3_ENDPOINT_URL: {{ $objectStorageEndpoint | quote }}
  {{- end }}
  {{- $objectStorageBucket := include "azents.objectStorageBucket" . }}
  {{- if $objectStorageBucket }}
  AZ_WORKSPACE_S3_BUCKET: {{ $objectStorageBucket | quote }}
  {{- end }}
  {{- if .Values.runtimeProviderKubernetes.enabled }}
  AZ_RUNTIME_RUNNER_IMAGE: {{ include "azents.runtimeRunnerImage" . | quote }}
  AZ_RUNTIME_RUNNER_CONTROL_ENDPOINT: {{ include "azents.runtimeControlEndpoint" . | quote }}
  {{- end }}
  {{- if .Values.server.mcpEgressProxy.enabled }}
  AZ_MCP_PROXY_URL: {{ printf "http://mcp-egress-proxy.%s.svc.cluster.local:3128" (include "azents.serverNamespace" .) | quote }}
  {{- end }}
{{- end }}
